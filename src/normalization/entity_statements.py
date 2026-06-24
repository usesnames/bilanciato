"""Normalize the civil-code financial statements (schema ex artt. 2424/2425 c.c.)
of a partecipata's *fascicolo di bilancio* PDF into long-format rows.

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
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

# -- categories ----------------------------------------------------------------
ATTIVO = "stato_patrimoniale_attivo"
PASSIVO = "stato_patrimoniale_passivo"
CONTO_ECONOMICO = "conto_economico"

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


@dataclass
class StatementItem:
    """One (voce x year) figure of a partecipata's civil-code statement."""

    category: str
    seq: int           # printed order of the voce within the statement
    code: str          # leading code token ("A.I.", "1)", "") — "" for totals/results
    name: str
    year: int
    value: Decimal
    is_total: bool
    related_party: str | None  # 'socio' | 'gruppo_socio' | 'controllate' | None
    source_page: int


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
    # collapse leftover leaders / whitespace
    name = re.sub(r"[_]{2,}", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" ._-")
    return name


def _code_of(label: str) -> str:
    m = _CODE_RE.match(label)
    return m.group(0) if m else ""


def normalize_statement(
    pages: dict[int, list[dict]], category: str, *, year: int, prev_year: int
) -> list[StatementItem]:
    """Normalize one statement category from a ``{page_no: extract_words()}`` map.

    Lines are read top-to-bottom across the given pages; wrapped labels merge into
    the preceding code-bearing voce. Each kept voce yields up to two items (current
    and prior year).
    """
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
                # continuation / wrapped label: extend the name, and fill the
                # figures if the code-bearing line itself had none.
                pending["name"] += " " + label
                if pending["cur"] is None and pending["prev"] is None:
                    pending["cur"], pending["prev"] = cur, prev
            # a fragment before any voce (page header) is ignored
    flush(pending)
    return items
