"""Per-capitolo (analytic) detail of the rendiconto della gestione.

The "RENDICONTO ... PER CAPITOLI" PDF is the *Conto di Bilancio D.Lgs 118
analitico*: the same conto del bilancio we already summarise per missione/titolo,
but exploded down to the single **capitolo**. It is the leaf layer beneath the
aggregates in the ``rendiconto`` table -- the capitoli of a missione sum exactly
to that missione's total (verified in ``validate``).

Structure (self-describing via running headings, not fixed page ranges):

* SPESE   -- TITOLO -> MISSIONE -> PROGRAMMA -> MACROAGGREGATO -> CAPITOLO
* ENTRATE -- TITOLO -> TIPOLOGIA -> CATEGORIA -> CAPITOLO

Each capitolo is a 3-line block of labelled values. Labels are unique per block
on the spese side, but on the entrate side CP/CS/TR each appear twice with
different meanings (previsioni vs maggiori/minori, riscossioni vs residui), so
those are disambiguated by order of occurrence. Subtotal blocks (introduced by a
"TOTALE ..." line and carrying no 12-digit capitolo code) are skipped: the
aggregates already live in the ``rendiconto`` table.

The drill-down tree exposed to the dashboard is uniform 3 levels + capitolo:
``liv1 -> liv2 -> liv3 -> capitolo`` where, by ``kind``:
    spesa   : liv1=missione, liv2=programma, liv3=macroaggregato
    entrata : liv1=titolo,   liv2=tipologia, liv3=categoria
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

# Value labels, longest-first so e.g. RR/RS/RC win over R and ECP wins over EC.
# A label may be glued to its value (seen in totals like "ECP1.624..."), hence \s*.
_LABELS = ["ECP", "FPV", "RS", "RR", "PR", "EP", "EC", "RC", "CP", "CS", "TP", "TR", "PC", "I", "A", "R"]
_LAB_RE = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(_LABELS) + r")\s*(-?[\d.]+,\d{2})")

# (label, nth-occurrence-in-block) -> canonical measure name. The three core
# measures reuse the exact names of the aggregate ``rendiconto`` table
# (previsioni / impegni|accertamenti / pagamenti_totali|riscossioni_totali) so the
# dashboard's "Misura" menu and the sum-to-aggregate cross-check line up.
_SPESA_MAP = {
    ("CP", 0): "previsioni", ("I", 0): "impegni", ("TP", 0): "pagamenti_totali",
    ("PC", 0): "pagamenti_c_competenza", ("PR", 0): "pagamenti_c_residui",
    ("RS", 0): "residui_iniziali", ("R", 0): "riaccertamento_residui",
    ("EP", 0): "residui_da_eserc_prec", ("ECP", 0): "economie_competenza",
    ("EC", 0): "residui_da_competenza", ("CS", 0): "previsioni_cassa",
    ("FPV", 0): "fpv", ("TR", 0): "residui_da_riportare",
}
_ENTRATA_MAP = {
    ("CP", 0): "previsioni", ("A", 0): "accertamenti", ("TR", 0): "riscossioni_totali",
    ("RC", 0): "riscossioni_c_competenza", ("RR", 0): "riscossioni_c_residui",
    ("RS", 0): "residui_iniziali", ("R", 0): "riaccertamento_residui",
    ("EP", 0): "residui_da_eserc_prec", ("CP", 1): "maggiori_minori_accertamenti",
    ("EC", 0): "residui_da_competenza", ("CS", 0): "previsioni_cassa",
    ("CS", 1): "maggiori_minori_cassa", ("TR", 1): "residui_da_riportare",
}

_HEADING_RE = re.compile(
    r"^(TITOLO|MISSIONE|PROGRAMMA|MACROAGGREGATO|TIPOLOGIA|CATEGORIA)\s+(\d+)\s*:\s*(.*)$"
)
# A capitolo line: 3-4 small leading integers then the capitolo code, then the
# denominazione (which may be glued to the code on the spese side). Real capitoli
# carry a 12-digit code. The FPV (fondo pluriennale vincolato) rows use a 9-digit
# placeholder code (e.g. "2 10 5 5 972510205 FPV - ..."); we still match them here
# so they act as a block boundary -- otherwise they glue onto the previous
# capitolo's denominazione -- but we do NOT record them (see normalize_capitoli):
# their codes are non-unique (the same 9-digit code is reused across missioni) and
# they carry I=0/TP=0, so dropping them leaves the impegni/pagamenti reconciliation
# untouched while keeping the capitolo namespace clean (unique 12-digit codes).
_CAPITOLO_RE = re.compile(r"^\s*(?:\d{1,3}\s+){2,4}(\d{9,12})\s*(.*)$")

# Page header/footer boilerplate. Each page repeats a fixed 10-line column-header
# band (top) plus a "Data di stampa ... Pagina N di M" footer. When a capitolo
# block straddles a page break these lines would otherwise be swallowed into the
# denominazione, so they are dropped. All markers are value-free header text; the
# reversed tokens (RGGAORCAM=MACROAGGR., OLOTIT=TITOLO, ENOISSIM=MISSIONE,
# AMMARGORP=PROGRAMMA, AIGOLOPIT=TIPOLOGIA, AIROGETAC=CATEGORIA) come from
# pdfplumber reading the rotated column labels. Matched on both spese and entrate
# layouts. Distinct from real "TOTALE MISSIONE/TITOLO/GENERALE" subtotal lines.
_BOILERPLATE_RE = re.compile(
    r"^("
    r"COMUNE DI TORINO"
    r"|Data di stampa"
    r"|\.?RGGAORCAM|OLOTIT|ENOISSIM|AMMARGORP|AIGOLOPIT|AIROGETAC"
    r"|CODICE$|CODICE PREVISIONI"
    r"|CAPITOLO$"
    r"|DENOMINAZIONE\b"
    r"|PREVISIONI DEFINITIVE DI"
    r"|CASSA \(CS\)"
    r"|RESIDUI (ATTIVI|PASSIVI) (AL|DA)"
    r"|\(RS\) PREC\."
    r"|RIPORT\. \(TR"
    r"|TOTALE RESIDUI (ATTIVI|PASSIVI) DA"
    r")"
)


def _is_boilerplate(line: str) -> bool:
    """A repeated page header/footer line (never carries a monetary value)."""
    if _LAB_RE.search(line):  # any "LABEL value" token => real data, keep it
        return False
    return bool(_BOILERPLATE_RE.match(line))


@dataclass
class CapitoloItem:
    kind: str            # 'spesa' | 'entrata'
    sezione: str | None  # spese: titolo (correnti/conto capitale/...); entrate: None
    liv1_code: str
    liv1_name: str
    liv2_code: str
    liv2_name: str
    liv3_code: str | None
    liv3_name: str | None
    capitolo_code: str
    denominazione: str
    measure: str
    value: Decimal
    page: int


def _to_decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(".", "").replace(",", "."))


def _emit_block(
    kind: str, code: str, text: str, page: int, ctx: dict
) -> list[CapitoloItem]:
    """Turn one capitolo block (joined text) into per-measure items."""
    # Denominazione = the block text with every "LABEL value" token stripped out.
    denom = re.sub(r"\s+", " ", _LAB_RE.sub(" ", text)).strip()
    mapping = _SPESA_MAP if kind == "spesa" else _ENTRATA_MAP
    seen: dict[str, int] = {}
    items: list[CapitoloItem] = []
    for m in _LAB_RE.finditer(text):
        label = m.group(1)
        occ = seen.get(label, 0)
        seen[label] = occ + 1
        measure = mapping.get((label, occ))
        if measure is None:
            continue
        items.append(CapitoloItem(
            kind=kind, sezione=ctx.get("sezione"),
            liv1_code=ctx["liv1_code"], liv1_name=ctx["liv1_name"],
            liv2_code=ctx["liv2_code"], liv2_name=ctx["liv2_name"],
            liv3_code=ctx.get("liv3_code"), liv3_name=ctx.get("liv3_name"),
            capitolo_code=code, denominazione=denom,
            measure=measure, value=_to_decimal(m.group(2)), page=page,
        ))
    return items


def normalize_capitoli(pages: list[tuple[int, str]]) -> list[CapitoloItem]:
    """Parse the analytic per-capitolo PDF text into long-format items.

    ``pages`` is ``[(page_number, page_text), ...]`` for the whole document; the
    spese/entrate side is detected per page from the page header.
    """
    items: list[CapitoloItem] = []
    kind = "entrata"
    ctx: dict = {}
    cur_code: str | None = None
    cur_page = 0
    buf: list[str] = []

    def flush():
        nonlocal cur_code, buf
        if cur_code is not None and buf:
            items.extend(_emit_block(kind, cur_code, " ".join(buf), cur_page, ctx))
        cur_code = None
        buf = []

    def set_heading(level: str, code: str, name: str):
        # Map the printed heading onto the uniform liv1/liv2/liv3 tree per kind.
        if kind == "spesa":
            if level == "TITOLO":
                ctx["sezione"] = name
            elif level == "MISSIONE":
                # zero-pad to match the aggregate ``rendiconto`` table (01..99).
                ctx["liv1_code"], ctx["liv1_name"] = code.zfill(2), name
                ctx["liv2_code"] = ctx["liv2_name"] = ctx["liv3_code"] = ctx["liv3_name"] = None
            elif level == "PROGRAMMA":
                ctx["liv2_code"], ctx["liv2_name"] = code, name
                ctx["liv3_code"] = ctx["liv3_name"] = None
            elif level == "MACROAGGREGATO":
                ctx["liv3_code"], ctx["liv3_name"] = code, name
        else:
            if level == "TITOLO":
                ctx["liv1_code"], ctx["liv1_name"] = code, name
                ctx["liv2_code"] = ctx["liv2_name"] = ctx["liv3_code"] = ctx["liv3_name"] = None
            elif level == "TIPOLOGIA":
                ctx["liv2_code"], ctx["liv2_name"] = code, name
                ctx["liv3_code"] = ctx["liv3_name"] = None
            elif level == "CATEGORIA":
                ctx["liv3_code"], ctx["liv3_name"] = code, name

    for page_no, text in pages:
        if "- SPESE (anno" in text:
            kind = "spesa"
        elif "- ENTRATE (anno" in text:
            kind = "entrata"
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if _is_boilerplate(line):
                continue  # repeated page header/footer: drop, keep the block open
            heading = _HEADING_RE.match(line)
            if heading:
                flush()
                set_heading(heading.group(1), heading.group(2), heading.group(3).strip())
                continue
            if line.upper().startswith("TOTALE"):
                flush()  # close the current capitolo; the subtotal block is skipped
                continue
            cap = _CAPITOLO_RE.match(line)
            if cap and "liv1_code" in ctx:
                flush()
                code = cap.group(1)
                if len(code) < 12:
                    # FPV placeholder row: boundary only -- close the previous
                    # capitolo cleanly, but don't open a block for it.
                    continue
                cur_code = code
                cur_page = page_no
                buf = [cap.group(2)]
                continue
            if cur_code is not None:
                buf.append(line)  # continuation of the open capitolo (denom wrap / value lines)
    flush()
    return items
