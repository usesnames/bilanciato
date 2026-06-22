"""Entity normalization (consolidation-area registry).

Parses the Gruppo Amministrazione Pubblica table into :class:`Entity` records.

Layout notes (Torino Bilancio Consolidato, p.24-25):

* ``col0`` = Denominazione, ``col1`` = capitale, ``col2`` = ownership quota.
* On p.24 a long quota spills into ``col3`` and onto continuation rows (blank
  ``col0``); the ``% voti`` columns sit further right and are ignored here.
* On p.25 the quota is a single percentage in ``col2``; ``col3+`` are ``% voti``.

``ownership_percentage`` is the sum of the percentages stated in the quota text
(direct + indirect), best-effort. ``consolidation_method`` is left ``None``: the
Integrale/Proporzionale classification is narrative in the source, not tabular.
The raw quota text is preserved in the extracted JSON for traceability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from src.extraction.pdf_tables import RawRow

_PCT_RE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")
_VOTI_MARKERS = {"non rilevante", "/", "-", ""}
_QUOTA_HINTS = ("diretta", "indiretta", "tramite", "%")

# header rows to skip
_HEADER_HINTS = ("denominazione", "quota posseduta", "% voti", "capitale")

_TYPE_RULES = [
    ("fondazione", ("FONDAZIONE",)),
    ("associazione", ("ASSOCIAZIONE",)),
    ("consorzio", ("CONSORZIO",)),
    ("comitato", ("COMITATO",)),
    ("istituzione", ("ISTITUZIONE",)),
    ("agenzia", ("AGENZIA", "AGENZIE")),
    ("società", ("S.P.A", "S.R.L", "S.C.AR.L", " SPA", " SRL")),
]


@dataclass
class Entity:
    name: str
    ownership_percentage: Decimal | None
    consolidation_method: str | None
    entity_type: str
    quota_text: str  # raw source text, preserved for traceability
    page: int


def _classify(name: str) -> str:
    upper = f" {name.upper()} "
    for label, needles in _TYPE_RULES:
        if any(n in upper for n in needles):
            return label
    return "altro"


def _parse_pct(text: str) -> Decimal | None:
    """Sum every percentage stated in the quota text (direct + indirect)."""
    matches = _PCT_RE.findall(text)
    if not matches:
        return None
    total = Decimal(0)
    for m in matches:
        total += Decimal(m.replace(".", "X").replace(",", ".").replace("X", "."))
    return total


def _is_header(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    return any(h in joined for h in _HEADER_HINTS)


def _quota_from_row(cells: list[str], main: bool) -> str:
    """Collect quota fragments from a row, excluding the % voti columns.

    For the main row, the quota is ``col2`` plus ``col3`` when ``col3`` looks
    like quota text (not a voti marker). For continuation rows (no name), every
    non-marker cell is quota spillover.
    """
    parts: list[str] = []
    if main:
        if len(cells) > 2 and cells[2]:
            parts.append(cells[2])
        if len(cells) > 3 and cells[3].lower() not in _VOTI_MARKERS:
            if any(h in cells[3].lower() for h in _QUOTA_HINTS):
                parts.append(cells[3])
    else:
        for c in cells:
            if c and c.lower() not in _VOTI_MARKERS and any(
                h in c.lower() for h in _QUOTA_HINTS
            ):
                parts.append(c)
    return " ".join(parts)


def normalize_entities(rows: list[RawRow]) -> list[Entity]:
    """Turn raw GAP-table rows into entity records, merging continuation rows."""
    entities: list[Entity] = []
    current: Entity | None = None

    for row in rows:
        cells = row.cells
        if _is_header(cells):
            continue
        name = cells[0] if cells else ""

        if name:  # start a new entity
            quota = _quota_from_row(cells, main=True)
            current = Entity(
                name=name,
                ownership_percentage=None,  # filled after quota fully assembled
                consolidation_method=None,
                entity_type=_classify(name),
                quota_text=quota,
                page=row.page,
            )
            entities.append(current)
        elif current is not None:  # continuation of the previous entity
            extra = _quota_from_row(cells, main=False)
            if extra:
                current.quota_text = f"{current.quota_text} {extra}".strip()

    for e in entities:
        e.ownership_percentage = _parse_pct(e.quota_text)
    return entities
