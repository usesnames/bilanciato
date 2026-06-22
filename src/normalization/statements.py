"""Normalization layer.

Turns raw extracted rows into clean, typed records. The transformations are
purely structural (whitespace, number parsing, column identification) -- no
financial value is ever altered (CLAUDE.md).

Strategy: rather than hardcode column positions (which differ between the income
statement and the balance sheet, and drift page to page), we *classify each
cell*:

* an **amount** is an Italian monetary value -- it must carry a decimal comma
  (``,dd``) so that bare line-item indices like ``7`` or reference codes are not
  mistaken for money;
* the **description** is the most text-heavy cell preceding the amounts;
* the **code** is the hierarchy path (e.g. ``A``, ``II.1``) sitting before the
  description.

The first amount is the current year (2024), the second the prior year (2023),
mirroring the printed column order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from src.extraction.pdf_tables import ExtractedSection
from src.utils.numbers import is_euro, parse_euro

# A code cell is a structural marker: a section letter (A, b), a roman numeral
# (II, III), or a (dotted) line number (7, 1.1, 5.12). Anything else before the
# amounts is description text.
_CODE_RE = re.compile(r"[A-Za-z]|[IVXLCDM]+|\d+(?:\.\d+)*")


def _is_amount(cell: str) -> bool:
    """A monetary value: looks like a euro amount *and* carries a decimal comma.

    The comma requirement excludes line numbers (``7``) and integer codes that
    would otherwise parse as numbers.
    """
    return "," in cell and is_euro(cell)


def _is_code(cell: str) -> bool:
    return bool(_CODE_RE.fullmatch(cell))


@dataclass
class NormalizedRow:
    """One normalized statement line."""

    table_type: str
    page: int
    code: str  # hierarchy path, e.g. "A", "II.1", "B.12.a" ("" if none)
    description: str
    value_2024: Decimal | None
    value_2023: Decimal | None
    is_metric: bool  # True when the row carries a current-year value


def normalize_row(table_type: str, page: int, cells: list[str]) -> NormalizedRow | None:
    """Normalize a single raw row. Returns ``None`` for rows with no content."""
    non_empty = [(i, c) for i, c in enumerate(cells) if c]
    if not non_empty:
        return None

    amount_idx = [i for i, c in non_empty if _is_amount(c)]
    first_amount = amount_idx[0] if amount_idx else len(cells)

    amounts = [parse_euro(cells[i]) for i in amount_idx]
    value_2024 = amounts[0] if len(amounts) >= 1 else None
    value_2023 = amounts[1] if len(amounts) >= 2 else None

    # Cells before the first amount: structural codes vs description text.
    # The description joins ALL text cells in order, so a label split across
    # cells (e.g. "TOTALE DEL" | "PASSIVO") is reconstructed whole.
    pre = [c for i, c in non_empty if i < first_amount]
    code = ".".join(c for c in pre if _is_code(c))
    description = " ".join(c for c in pre if not _is_code(c))

    # A row with no description and no value is noise (e.g. stray ref fragments).
    if not description and value_2024 is None:
        return None

    return NormalizedRow(
        table_type=table_type,
        page=page,
        code=code,
        description=description,
        value_2024=value_2024,
        value_2023=value_2023,
        is_metric=value_2024 is not None,
    )


def normalize_section(section: ExtractedSection) -> list[NormalizedRow]:
    """Normalize every row of an extracted section, preserving order."""
    out: list[NormalizedRow] = []
    for raw in section.rows:
        row = normalize_row(section.table_type, raw.page, raw.cells)
        if row is not None:
            out.append(row)
    return out
