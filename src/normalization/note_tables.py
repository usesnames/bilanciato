"""Nota integrativa detail-table normalization.

The nota integrativa (p.37-51) carries many heterogeneous tables. Three shapes
recur and are normalized here into a single long-format list of
:class:`NoteItem` records (one row per voce x period):

* **movimenti** -- "Valore di inizio esercizio | Variazione | Valore di fine"
* **confronto** -- "31.12.2023 | Variazione | 31.12.2024"
* **dettaglio** -- "Descrizione | 31.12.2024" (single value)

Each table is classified by its header; each data row is reduced to its voce
(most text-heavy leading cell) and its ordered monetary amounts, which are then
mapped onto the period labels of that table kind. Values are parsed, never
altered. Tables that match none of the shapes are skipped (not guessed at).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from src.extraction.pdf_tables import PageTable
from src.utils.numbers import is_euro, parse_euro

_ALPHA_RE = re.compile(r"[A-Za-zÀ-ÿ]")

# (kind, period labels) keyed by a marker found in the table header.
_KINDS = {
    "movimenti": ("valore di inizio", ["inizio", "variazione", "fine"]),
    "confronto": ("31.12.2023", ["2023", "variazione", "2024"]),
}


@dataclass
class NoteItem:
    page: int
    table_index: int
    heading: str  # section heading on the page (e.g. "5.12 DEBITI")
    kind: str
    voce: str
    period: str
    value: Decimal
    unit: str = "EUR"


def _is_amount(cell: str) -> bool:
    return "," in cell and is_euro(cell)


def _alpha(cell: str) -> int:
    return len(_ALPHA_RE.findall(cell))


def _classify(table: PageTable) -> tuple[str, list[str]] | None:
    header = " ".join(" ".join(r) for r in table.rows[:3]).lower()
    for kind, (marker, labels) in _KINDS.items():
        if marker in header:
            return kind, labels
    # single-value detail table: "Descrizione | 31.12.2024"
    if "descrizione" in header and "31.12" in header:
        return "dettaglio", ["2024"]
    return None


def _row_voce_amounts(cells: list[str]) -> tuple[str, list[Decimal]]:
    non_empty = [(i, c) for i, c in enumerate(cells) if c]
    amount_idx = [i for i, c in non_empty if _is_amount(c)]
    if not amount_idx:
        return "", []
    first = amount_idx[0]
    pre = [(i, c) for i, c in non_empty if i < first]
    voce = max(pre, key=lambda ic: _alpha(ic[1]))[1] if pre else ""
    amounts = [parse_euro(cells[i]) for i in amount_idx]
    return voce, [a for a in amounts if a is not None]


def normalize_note_tables(tables: list[PageTable]) -> list[NoteItem]:
    """Normalize classified nota-integrativa tables into long-format items."""
    items: list[NoteItem] = []
    for table in tables:
        classified = _classify(table)
        if classified is None:
            continue
        kind, labels = classified
        for cells in table.rows:
            voce, amounts = _row_voce_amounts(cells)
            if not voce or _alpha(voce) < 3 or not amounts:
                continue
            for i, value in enumerate(amounts):
                period = labels[i] if i < len(labels) else f"v{i + 1}"
                items.append(
                    NoteItem(table.page, table.index, table.heading, kind, voce, period, value)
                )
    return items
