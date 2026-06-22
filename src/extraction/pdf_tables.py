"""Extraction layer.

Pulls raw tables out of the PDF using **pdfplumber**.

Engine choice: CLAUDE.md lists tabula-py as preferred, but on the Torino
Bilancio Consolidato tabula merges descriptions into the numeric columns and
splits cells across rows, losing the 2024/2023 separation. pdfplumber keeps the
columns aligned and is pure-Python (no Java dependency), which better serves the
project's #1/#3 priorities (financial correctness, reproducibility). tabula
remains a viable fallback for layouts where pdfplumber under-segments.

This layer does NOT interpret values. It only captures cells verbatim, tagged
with the page they came from, so every downstream value stays traceable to a
PDF page.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber

from src.utils.config import EXTRACTED, DocumentProfile


@dataclass
class RawRow:
    """One extracted table row, tagged with its source page (1-based)."""

    page: int
    cells: list[str]


@dataclass
class ExtractedSection:
    """All raw rows for one statement section of a document."""

    table_type: str
    page_start: int
    page_end: int
    rows: list[RawRow]


def _clean(cell: str | None) -> str:
    """Collapse internal newlines/whitespace in a cell, never dropping content."""
    if cell is None:
        return ""
    return " ".join(cell.split())


def extract_section(pdf: pdfplumber.PDF, section) -> ExtractedSection:
    """Extract all table rows for one :class:`StatementSection`."""
    rows: list[RawRow] = []
    for pno in section.pages():
        page = pdf.pages[pno - 1]
        for table in page.extract_tables():
            for raw in table:
                cells = [_clean(c) for c in raw]
                if any(cells):  # skip fully blank rows
                    rows.append(RawRow(page=pno, cells=cells))
    return ExtractedSection(
        table_type=section.table_type,
        page_start=section.page_start,
        page_end=section.page_end,
        rows=rows,
    )


def extract_entity_rows(pdf: pdfplumber.PDF, pages: tuple[int, ...]) -> list[RawRow]:
    """Extract rows of the main entity table (Gruppo Amministrazione Pubblica).

    Each listed page carries the GAP registry as its *largest* table plus small
    fragment tables (wrapped-cell spillover). We take the largest table per page,
    which holds the name / capital / ownership columns in aligned form.
    """
    rows: list[RawRow] = []
    for pno in pages:
        tables = pdf.pages[pno - 1].extract_tables()
        if not tables:
            continue
        main = max(tables, key=len)
        for raw in main:
            cells = [_clean(c) for c in raw]
            if any(cells):
                rows.append(RawRow(page=pno, cells=cells))
    return rows


@dataclass
class PageTable:
    """One table on a page, with the page's section heading for context."""

    page: int
    index: int
    heading: str
    rows: list[list[str]]


# Numbered nota-integrativa headings, e.g. "5.7 DISPONIBILITÀ LIQUIDE", "5.12 DEBITI".
_HEADING_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+[A-ZÀ-Ü][A-ZÀ-Ü ']{3,}")


def _page_heading(page: pdfplumber.page.Page) -> str:
    for line in (page.extract_text() or "").splitlines():
        if _HEADING_RE.match(line):
            return line.strip()
    return ""


def extract_note_tables(
    pdf: pdfplumber.PDF, pages: tuple[int, ...], min_rows: int = 3
) -> list[PageTable]:
    """Extract every sizable table on the given (nota integrativa) pages."""
    out: list[PageTable] = []
    for pno in pages:
        page = pdf.pages[pno - 1]
        heading = _page_heading(page)
        for idx, table in enumerate(page.extract_tables()):
            if len(table) < min_rows:
                continue
            rows = [[_clean(c) for c in r] for r in table]
            out.append(PageTable(page=pno, index=idx, heading=heading, rows=rows))
    return out


def extract_document(pdf_path: Path, profile: DocumentProfile) -> list[ExtractedSection]:
    """Extract every section declared in the document profile."""
    sections: list[ExtractedSection] = []
    with pdfplumber.open(pdf_path) as pdf:
        for section in profile.sections:
            sections.append(extract_section(pdf, section))
    return sections


def save_raw(doc_name: str, sections: list[ExtractedSection]) -> Path:
    """Persist raw extracted rows as JSON (preserving page provenance).

    Returns the output directory. Raw extracts are the audit trail: they capture
    exactly what came off the page before any normalization.
    """
    out_dir = EXTRACTED / doc_name
    out_dir.mkdir(parents=True, exist_ok=True)
    for section in sections:
        payload = {
            "table_type": section.table_type,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "rows": [asdict(r) for r in section.rows],
        }
        (out_dir / f"{section.table_type}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2)
        )
    return out_dir
