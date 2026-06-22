"""Per-entity financial figures from the nota integrativa.

Two clean per-entity tables are normalized here into a single long-format list
of :class:`EntityMetric` records (one row per entity x figure):

* **Spesa personale (p.55, "6.3 Ulteriori dati")** -- per consolidated entity:
  consolidation %, revenue incidence on the Comune, personnel cost (voce B9),
  losses covered by the Comune in the last three years.
* **Valutazione partecipazioni (p.131-133)** -- per participated organism:
  ownership %, carrying value of the participation in the Comune's balance
  sheet, the organism's net equity at 31.12.2024, the consolidated fraction of
  that equity, the elimination difference, and the elimination entry id.

Values are parsed but never altered. Percentages carry unit ``PCT``; monetary
figures carry unit ``EUR``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from src.extraction.pdf_tables import RawRow
from src.utils.numbers import parse_euro

_NREG_RE = re.compile(r"\bE[PI]\s*\d+\b")


@dataclass
class EntityMetric:
    entity_name: str
    source: str  # personale | valutazione_diretta | valutazione_indiretta
    metric_name: str
    value: Decimal | None
    unit: str  # EUR | PCT
    page: int
    note: str | None = None  # e.g. elimination entry id


def _parse_pct(text: str) -> Decimal | None:
    """Parse a plain percentage like '60,37%' or '3,163' (no thousands dots)."""
    raw = text.strip().rstrip("%").strip().replace(",", ".")
    if not raw or raw in {"-", "/"}:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


# --- p.55 personnel table --------------------------------------------------
def normalize_personnel(rows: list[RawRow]) -> list[EntityMetric]:
    """Columns: name | consolidation % | revenue incidence % | personnel EUR | losses EUR."""
    out: list[EntityMetric] = []
    for r in rows:
        c = r.cells
        name = c[0] if c else ""
        joined = " ".join(c).lower()
        if not name or "organismo" in joined or "percentuale" in joined:
            continue
        if len(c) < 5:
            continue
        specs = [
            ("perc_consolidamento", _parse_pct(c[1]), "PCT"),
            ("incidenza_ricavi_comune", _parse_pct(c[2]), "PCT"),
            ("spesa_personale", parse_euro(c[3]), "EUR"),
            ("perdite_ripianate_comune", parse_euro(c[4]), "EUR"),
        ]
        for metric_name, value, unit in specs:
            if value is not None:
                out.append(EntityMetric(name, "personale", metric_name, value, unit, r.page))
    return out


# --- p.131-133 participation valuation -------------------------------------
# Column maps differ by page width (direct pages are wider than the indirect one).
_MAP_WIDE = {"quota": 1, "importo": 3, "pn": 5, "fraz": 7, "diff": 9, "nreg": 11}
_MAP_NARROW = {"quota": 1, "importo": 2, "pn": 4, "fraz": 5, "diff": 6, "nreg": 7}


def _merge_block(block: list[list[str]]) -> list[str]:
    """Union of non-empty cells per column across an entity's name+value rows."""
    width = max(len(r) for r in block)
    merged = [""] * width
    for row in block:
        for i, cell in enumerate(row):
            if cell and not merged[i]:
                merged[i] = cell
    return merged


def _is_name_row(cells: list[str]) -> bool:
    """A row that introduces an entity: text in col0, no euro figure present."""
    if not cells or not cells[0]:
        return False
    head = cells[0].lower()
    if any(h in head for h in ("organismo", "valutazione", "quota")):
        return False
    return not any(parse_euro(x) is not None and "," in x for x in cells[1:])


def normalize_valuation(rows: list[RawRow]) -> list[EntityMetric]:
    """Parse the direct/indirect participation-valuation tables."""
    out: list[EntityMetric] = []

    # group rows into per-entity blocks (a name row plus following value rows)
    blocks: list[tuple[int, list[list[str]]]] = []
    current: list[list[str]] | None = None
    page = 0
    for r in rows:
        if _is_name_row(r.cells):
            current = [r.cells]
            blocks.append((r.page, current))
            page = r.page
        elif current is not None and any(r.cells):
            current.append(r.cells)

    for blk_page, block in blocks:
        merged = _merge_block(block)
        cmap = _MAP_WIDE if len(merged) >= 12 else _MAP_NARROW
        name = merged[0]
        source = "valutazione_indiretta" if blk_page == 133 else "valutazione_diretta"

        def cell(key: str) -> str:
            i = cmap[key]
            return merged[i] if i < len(merged) else ""

        nreg_match = _NREG_RE.search(" ".join(merged))
        nreg = nreg_match.group(0).replace(" ", " ") if nreg_match else None

        specs = [
            ("quota_posseduta", _parse_pct(cell("quota")), "PCT"),
            ("valore_iscrizione_partecipazione", parse_euro(cell("importo")), "EUR"),
            ("patrimonio_netto", parse_euro(cell("pn")), "EUR"),
            ("frazione_patrimonio_netto", parse_euro(cell("fraz")), "EUR"),
            ("differenza_elisione", parse_euro(cell("diff")), "EUR"),
        ]
        for metric_name, value, unit in specs:
            if value is not None:
                out.append(EntityMetric(name, source, metric_name, value, unit, blk_page, nreg))
    return out


# --- "paired-row" layout (Bilancio Consolidato 2021) -----------------------
# In the 2021 report both per-entity tables are laid out as a *name row*
# (a single text cell) immediately followed by a *value row* whose numeric
# cells, once the blank padding columns are dropped, appear in a fixed order.
# pdfplumber shifts the physical column positions per page, so we parse by the
# order of the non-empty cells rather than by absolute index.
def _pair_rows(rows: list[RawRow]):
    """Yield ``(name, value_cells, page)`` for the paired name/value layout.

    A name row is a single non-empty text cell; the following row carries the
    figures. Multi-line header fragments are also single-cell text rows, but a
    real entity name always immediately precedes the value row, so the transient
    fragment names are overwritten before a value row consumes them.
    """
    name: str | None = None
    for r in rows:
        cells = [c.strip() for c in r.cells if c and c.strip()]
        if not cells:
            continue
        numericish = sum(
            1 for c in cells if parse_euro(c) is not None or _parse_pct(c) is not None
        )
        if len(cells) == 1 and re.search(r"[A-Za-z]", cells[0]):
            name = cells[0]
        elif name and numericish >= 3:
            yield name, cells, r.page
            name = None


def normalize_personnel_paired(rows: list[RawRow]) -> list[EntityMetric]:
    """2021 "6.3 Ulteriori dati" personnel table (paired-row layout).

    Value-row order (blanks dropped): personnel EUR, consolidation %,
    revenue incidence %, losses covered EUR.
    """
    out: list[EntityMetric] = []
    for name, cells, page in _pair_rows(rows):
        if len(cells) < 4:
            continue
        specs = [
            ("perc_consolidamento", _parse_pct(cells[1]), "PCT"),
            ("incidenza_ricavi_comune", _parse_pct(cells[2]), "PCT"),
            ("spesa_personale", parse_euro(cells[0]), "EUR"),
            ("perdite_ripianate_comune", parse_euro(cells[3]), "EUR"),
        ]
        for metric_name, value, unit in specs:
            if value is not None:
                out.append(EntityMetric(name, "personale", metric_name, value, unit, page))
    return out


def normalize_valuation_paired(
    rows: list[RawRow], indirect_pages: tuple[int, ...] = ()
) -> list[EntityMetric]:
    """2021 participation-valuation tables (paired-row layout).

    Value-row order (blanks dropped): quota %, carrying value EUR, organism net
    equity EUR, consolidated fraction of equity EUR, elimination difference EUR,
    elimination entry id. Pages in ``indirect_pages`` are tagged indirect.
    """
    out: list[EntityMetric] = []
    for name, cells, page in _pair_rows(rows):
        if len(cells) < 5:
            continue
        nreg_match = _NREG_RE.search(" ".join(cells))
        nreg = nreg_match.group(0) if nreg_match else None
        source = "valutazione_indiretta" if page in indirect_pages else "valutazione_diretta"
        specs = [
            ("quota_posseduta", _parse_pct(cells[0]), "PCT"),
            ("valore_iscrizione_partecipazione", parse_euro(cells[1]), "EUR"),
            ("patrimonio_netto", parse_euro(cells[2]), "EUR"),
            ("frazione_patrimonio_netto", parse_euro(cells[3]), "EUR"),
            ("differenza_elisione", parse_euro(cells[4]), "EUR"),
        ]
        for metric_name, value, unit in specs:
            if value is not None:
                out.append(EntityMetric(name, source, metric_name, value, unit, page, nreg))
    return out
