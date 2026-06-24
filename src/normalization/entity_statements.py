"""Normalize financial statements of partecipate PDFs into long-format rows.

Supports two schemas:
* **Civil code** (artt. 2424/2425 c.c.) — e.g. Infratrasporti.TO (unlisted).
* **IAS/IFRS** — e.g. Iren S.p.A. (listed company, bilancio separato).

Civil-code overview:

The deposited bilancio of a società (e.g. Infratrasporti.To) contains, among much
narrative we ignore, the two prospetti we care about:

* **Stato patrimoniale** — Attivo (classes A/B/C/D) and Passivo (A/B/C/D/E);
* **Conto economico** — value/cost of production (A/B), financial (C), value
  adjustments (D), result.

Both are printed with TWO value columns: the current year (``Totale``) and the
prior year (``Totale Esercizio precedente``). We capture both: every printed line
becomes one row per year, mirroring how ``metrics`` stores the consolidato.

Extraction is **coordinate-based** (``extract_words`` + x-position), not text
regex, because the dotted leaders ("____") that fill the line up to the figure get
merged into the text by ``extract_text`` and corrupt the digits. Column rule,
robust across the whole schema:

* the prior-year figure is the numeric token at the far right (x1 ≳ 548);
* the current-year figure is the right-most numeric token left of it — this picks
  the ``Totale`` column whether it sits at the normal x (~432), the bold-total x
  (~499) or the sub-line x (~377), and ignores the ``Entro/Oltre 12 mesi`` break-
  down columns (x1 ≲ 390) that appear on crediti/debiti rows.

Wrapped labels (a voce whose text spills onto the next line, sometimes carrying the
figures) are merged back into the code-bearing voce; memo lines (``valore al lordo``
/ ``meno: fondo`` / ``di cui``) are truncated from the name but their figures fill a
voce that had none (e.g. *14) Oneri diversi di gestione*, whose amount prints on the
``di cui minusvalenze`` line).

IAS/IFRS overview:

Listed companies (e.g. Iren S.p.A.) use a 4-column layout per page:
  [current year | current related-party | prior year | prior related-party]
Only the first and third columns are captured. Labels are left-aligned (x0 < 255);
note references ``(1)``..``(99)`` appear just to their right and are excluded.
Multi-line labels (where the label is split across the value row) are merged using
a 10 px proximity test.

The related-party supplement (pages 488-489) lists amounts in *migliaia di euro*
for each counterparty including ``Comune di Torino``; these are stored with
``related_party`` set to the entity name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

# -- categories ----------------------------------------------------------------
ATTIVO = "stato_patrimoniale_attivo"
PASSIVO = "stato_patrimoniale_passivo"
CONTO_ECONOMICO = "conto_economico"

# ── civil-code column thresholds ──────────────────────────────────────────────
# x1 (right edge) threshold separating the prior-year column from everything left.
_PREV_X1_MIN = 548.0
# x1 floor below which a token is a breakdown column (Entro/Oltre 12 mesi), never
# a year total. Used only to bound the search for the current-year figure.
_CUR_X1_MIN = 250.0

# Memo phrases: the name is truncated here (their figures may still fill a voce).
_MEMO_CUT = re.compile(
    r"\b(valore al lordo|meno\s*:?\s*fondo|meno fondo|di cui|entro 12|oltre 12)\b",
    re.IGNORECASE,
)

# A line is a new structural voce if it opens with one of these codes …
_CODE_RE = re.compile(
    r"^(?:"
    r"[A-E]\)"                      # macro class:  A)  B)  C)  D)  E)
    r"|[A-E]\.[IVX]+\."             # roman subclass:  A.I.  B.III.  C.IV.
    r"|[A-E]\.(?![IVX])"            # macro class with a dot:  D. RATEI E RISCONTI
    r"|\d{1,2}(?:-(?:bis|ter|quater))?\)"   # numbered:  1)  21)  5-bis)
    r"|\d{1,2}\s+bis\)"             # numbered variant:  11 bis)
    r"|\d{1,2}(?=\s+[A-Z][a-z]{2})"  # numbered without paren:  20 Imposte
    r"|[a-z](?:-bis)?[.\)]"         # lettered:  a)  d.  d-bis)
    r")",
)
# … or it is a total / result line (matched on the space-compacted upper text, so
# the spaced "T O T A L E   A T T I V O" grand totals are caught too).
_TOTAL_PREFIXES = ("TOTALE", "RISULTATO", "DIFFERENZATRA", "UTILE(PERDITA)DELL")

# ── IAS/IFRS column thresholds ────────────────────────────────────────────────
_IFRS_NOTE_PAT = re.compile(r"^\(\d{1,2}\)$")
_IFRS_LABEL_X0_MAX = 255.0
_IFRS_SKIP_TOP = 70.0
_IFRS_MULTILINE_TOL = 10.0   # px between row tops to consider a split label

# 4-column SP/CE layout: cur | cur_party | prv | prv_party
_IFRS_CUR_X1_MAX = 370.0
_IFRS_PRV_X1_MIN = 430.0
_IFRS_PRV_X1_MAX = 495.0

_IFRS_TOTAL_FIRST = frozenset({"totale", "risultato", "margine", "ebit", "ebitda"})

# Related-party table: right-edge boundaries separating the 5 value columns.
# Observed on pages 488-489: dashes land at x1 ≈ 308, 366, 423, 477, 535.
_RP_COL_BOUNDS = (336.0, 393.0, 450.0, 506.0)

# Column names and SP/CE category for each of the five columns on page 488.
_RP_P488_COLS: tuple[tuple[str, str], ...] = (
    ("Crediti Commerciali",                       ATTIVO),
    ("Crediti Finanziari e Disponibilità liquide", ATTIVO),
    ("Crediti di altra natura",                   ATTIVO),
    ("Debiti Commerciali",                        PASSIVO),
    ("Debiti Finanziari",                         PASSIVO),
)
# … and for page 489.
_RP_P489_COLS: tuple[tuple[str, str], ...] = (
    ("Debiti di altra natura",  PASSIVO),
    ("Ricavi e altri proventi", CONTO_ECONOMICO),
    ("Costi e altri oneri",     CONTO_ECONOMICO),
    ("Proventi finanziari",     CONTO_ECONOMICO),
    ("Oneri finanziari",        CONTO_ECONOMICO),
)


@dataclass
class StatementItem:
    """One (voce x year) figure from a partecipata's statement."""

    category: str
    seq: int           # printed order of the voce within the statement
    code: str          # leading code token ("A.I.", "1)", "") — "" for totals/results
    name: str
    year: int
    value: Decimal
    is_total: bool
    related_party: str | None
    source_page: int


# ── shared helpers ─────────────────────────────────────────────────────────────

def _parse_amount(tok: str) -> int | None:
    """Parse one Italian-formatted integer token (``1.515.214.893``, ``(231.334)``),
    tolerating merged dotted leaders (``O____21_6_._1_72``). Returns ``None`` if the
    token carries no number."""
    s = tok.strip().rstrip("_").rstrip("-").rstrip(".")
    m = re.search(r"\(?\d[\d._]*\d\)?$|\(?\d\)?$", s)
    if not m:
        return None
    blob = m.group(0)
    neg = blob.startswith("(")
    blob = blob.strip("()").replace("_", "")
    if not re.fullmatch(r"\d{1,3}(\.\d{3})*|\d+", blob):
        return None
    val = int(blob.replace(".", ""))
    return -val if neg else val


def _cluster_rows(words: list[dict], tol: float = 3.5) -> list[list[dict]]:
    """Group words into visual rows by baseline (``top``), tolerant of the small
    baseline drift between a spaced title and its right-aligned figures."""
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


# ── civil-code parser ──────────────────────────────────────────────────────────

def _row_cells(ws: list[dict]) -> tuple[str, int | None, int | None]:
    """Split a visual row into (label, current_year, prior_year)."""
    prev: int | None = None
    cur: int | None = None
    cur_x1 = -1.0
    label: list[str] = []
    for i, w in enumerate(ws):
        v = _parse_amount(w["text"])
        # "12" in "Entro 12 mesi" / "Oltre 12 mesi" is a column header, not a figure.
        nxt = ws[i + 1]["text"].lower() if i + 1 < len(ws) else ""
        if v is not None and nxt == "mesi":
            v = None
        if v is not None and w["x1"] >= _PREV_X1_MIN:
            prev = v
        elif v is not None and w["x1"] >= _CUR_X1_MIN and w["x1"] > cur_x1:
            cur, cur_x1 = v, w["x1"]
        elif v is not None and w["x1"] >= _CUR_X1_MIN:
            pass  # a breakdown column further left than the current best
        else:
            label.append(w["text"])
    return " ".join(label).strip(), cur, prev


def _is_total(compact_upper: str) -> bool:
    return compact_upper.startswith(_TOTAL_PREFIXES)


def _related_party(name: str) -> str | None:
    n = name.lower()
    if "controllo delle controllanti" in n or "controllo di controllanti" in n:
        return "gruppo_socio"
    if "controllanti" in n or "controllante" in n:
        return "socio"
    if "controllate" in n or "collegate" in n:
        return "controllate"
    return None


def _clean_name(name: str) -> str:
    m = _MEMO_CUT.search(name)
    if m:
        name = name[: m.start()]
    name = re.sub(r"[_]{2,}", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" ._-")
    return name


def _code_of(label: str) -> str:
    m = _CODE_RE.match(label)
    return m.group(0) if m else ""


def normalize_statement(
    pages: dict[int, list[dict]], category: str, *, year: int, prev_year: int
) -> list[StatementItem]:
    """Normalize one civil-code statement category from a ``{page_no: words}`` map."""
    items: list[StatementItem] = []
    pending: dict | None = None
    seq = 0

    def flush(p: dict | None) -> None:
        nonlocal seq
        if not p:
            return
        name = _clean_name(p["name"])
        if not name:
            return
        code = _code_of(name)
        is_tot = p["is_total"] or _is_total(name.replace(" ", "").upper())
        rp = _related_party(name)
        emitted = False
        for yr, val in ((year, p["cur"]), (prev_year, p["prev"])):
            if val is None:
                continue
            items.append(StatementItem(
                category=category, seq=seq, code=code, name=name, year=yr,
                value=Decimal(val), is_total=is_tot, related_party=rp,
                source_page=p["page"]))
            emitted = True
        if emitted:
            seq += 1

    for page_no in sorted(pages):
        for ws in _cluster_rows(pages[page_no]):
            label, cur, prev = _row_cells(ws)
            if not label:
                continue
            compact = label.replace(" ", "").upper()
            starts_voce = bool(_CODE_RE.match(label)) or _is_total(compact)
            if starts_voce:
                flush(pending)
                pending = {"name": label, "cur": cur, "prev": prev,
                           "is_total": _is_total(compact), "page": page_no}
            elif pending is not None:
                pending["name"] += " " + label
                if pending["cur"] is None and pending["prev"] is None:
                    pending["cur"], pending["prev"] = cur, prev
    flush(pending)
    return items


# ── IAS/IFRS parser ────────────────────────────────────────────────────────────

def _ifrs_row_values(ws: list[dict]) -> tuple[int | None, int | None]:
    """Extract (cur_year, prev_year) from an IAS/IFRS row.

    4-column layout: cur | cur_party | prv | prv_party.  Only col1 and col3 are
    captured; note refs like ``(15)`` are skipped.
    """
    cur: int | None = None
    prv: int | None = None
    cur_x1 = prv_x1 = -1.0
    for w in ws:
        if _IFRS_NOTE_PAT.match(w["text"]):
            continue
        v = _parse_amount(w["text"])
        if v is None:
            continue
        x1 = w["x1"]
        if x1 <= _IFRS_CUR_X1_MAX:
            if x1 > cur_x1:
                cur, cur_x1 = v, x1
        elif _IFRS_PRV_X1_MIN <= x1 <= _IFRS_PRV_X1_MAX:
            if x1 > prv_x1:
                prv, prv_x1 = v, x1
    return cur, prv


def _ifrs_label_text(ws: list[dict]) -> str:
    parts = [w["text"] for w in sorted(ws, key=lambda x: x["x0"])
             if w["x0"] < _IFRS_LABEL_X0_MAX
             and not _IFRS_NOTE_PAT.match(w["text"])]
    return " ".join(parts).strip()


def _ifrs_is_total(label: str) -> bool:
    if not label:
        return False
    first = label.split()[0].lower()
    return first in _IFRS_TOTAL_FIRST or (label == label.upper() and len(label) > 1)


def normalize_statement_ifrs(
    pages: dict[int, list[dict]], category: str, *, year: int, prev_year: int
) -> list[StatementItem]:
    """Normalize one IAS/IFRS statement section.

    Handles the 4-column layout and multi-line labels where a label fragment
    sits on the row immediately above or below the value row (≤ 10 px apart).
    """
    items: list[StatementItem] = []
    seq = 0

    all_rows: list[tuple[int, list[dict]]] = []
    for page_no in sorted(pages):
        for ws in _cluster_rows(pages[page_no]):
            if not ws or ws[0]["top"] < _IFRS_SKIP_TOP:
                continue
            all_rows.append((page_no, ws))

    consumed: set[int] = set()
    i = 0
    while i < len(all_rows):
        if i in consumed:
            i += 1
            continue

        page_no, ws = all_rows[i]
        cur, prv = _ifrs_row_values(ws)

        if cur is None and prv is None:
            i += 1
            continue

        label = _ifrs_label_text(ws)
        top = ws[0]["top"]

        # Merge a label-only row immediately above (split label, first fragment above)
        if i > 0 and (i - 1) not in consumed:
            _, prev_ws = all_rows[i - 1]
            if (_ifrs_row_values(prev_ws) == (None, None)
                    and abs(top - prev_ws[0]["top"]) <= _IFRS_MULTILINE_TOL):
                pl = _ifrs_label_text(prev_ws)
                if pl:
                    label = (pl + " " + label).strip()

        # Merge a label-only row immediately below (split label, second fragment below)
        if i + 1 < len(all_rows) and (i + 1) not in consumed:
            _, next_ws = all_rows[i + 1]
            if (_ifrs_row_values(next_ws) == (None, None)
                    and abs(next_ws[0]["top"] - top) <= _IFRS_MULTILINE_TOL):
                nl = _ifrs_label_text(next_ws)
                if nl:
                    label = (label + " " + nl).strip()
                    consumed.add(i + 1)

        if not label:
            i += 1
            continue

        is_tot = _ifrs_is_total(label)
        for yr, val in ((year, cur), (prev_year, prv)):
            if val is None:
                continue
            items.append(StatementItem(
                category=category, seq=seq, code="", name=label,
                year=yr, value=Decimal(val), is_total=is_tot,
                related_party=None, source_page=page_no))
        seq += 1
        i += 1

    return items


def _rp_col_index(x1: float) -> int:
    """Map a word's right edge to a 0-based column index in the related-party table."""
    for idx, bound in enumerate(_RP_COL_BOUNDS):
        if x1 <= bound:
            return idx
    return len(_RP_COL_BOUNDS)


def normalize_rapporti_ifrs(
    pages_488: dict[int, list[dict]],
    pages_489: dict[int, list[dict]],
    *,
    year: int,
    entity: str = "Comune di Torino",
    migliaia: int = 1000,
) -> list[StatementItem]:
    """Extract one counterparty's row from IREN's related-party supplement.

    Pages 488-489 have a 5-column layout each (different column names per page).
    Values are in *migliaia di euro*; multiply by ``migliaia`` to get full euros.
    Only non-zero cells are stored.
    """
    items: list[StatementItem] = []
    seq = 0

    for pages, col_defs in (
        (pages_488, _RP_P488_COLS),
        (pages_489, _RP_P489_COLS),
    ):
        for page_no in sorted(pages):
            for ws in _cluster_rows(pages[page_no]):
                if not ws or ws[0]["top"] < _IFRS_SKIP_TOP:
                    continue
                label_words = [w["text"] for w in ws if w["x0"] < _IFRS_LABEL_X0_MAX]
                if entity.lower() not in " ".join(label_words).lower():
                    continue
                for w in ws:
                    if w["x0"] < _IFRS_LABEL_X0_MAX:
                        continue
                    v = _parse_amount(w["text"])
                    if v is None or v == 0:
                        continue
                    col = _rp_col_index(w["x1"])
                    if col >= len(col_defs):
                        continue
                    col_name, cat = col_defs[col]
                    items.append(StatementItem(
                        category=cat, seq=seq, code="", name=col_name,
                        year=year, value=Decimal(v * migliaia), is_total=False,
                        related_party=entity, source_page=page_no))
                    seq += 1

    return items
