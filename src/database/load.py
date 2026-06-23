"""Load normalized data into DuckDB.

Ingestion is idempotent at the document level: a document whose checksum is
already registered is not re-imported (CLAUDE.md: "Checksums prevent duplicate
imports").
"""

from __future__ import annotations

import json
from datetime import datetime

import duckdb

from src.extraction.pdf_tables import ExtractedSection
from src.normalization.entities import Entity
from src.normalization.entity_financials import EntityMetric
from src.normalization.entity_names import canonicalize
from src.normalization.debito import DebitoItem
from src.normalization.note_tables import NoteItem
from src.normalization.rendiconto import RendicontoItem
from src.normalization.rendiconto_capitoli import CapitoloItem
from src.normalization.statements import NormalizedRow


def _next_id(con: duckdb.DuckDBPyConnection, table: str) -> int:
    row = con.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}").fetchone()
    return int(row[0])


def document_exists(con: duckdb.DuckDBPyConnection, checksum: str) -> int | None:
    """Return the id of an already-imported document with this checksum, if any."""
    row = con.execute(
        "SELECT id FROM documents WHERE checksum = ?", [checksum]
    ).fetchone()
    return int(row[0]) if row else None


def insert_document(
    con: duckdb.DuckDBPyConnection,
    *,
    filename: str,
    checksum: str,
    document_type: str,
    year: int,
    page_count: int,
    upload_timestamp: datetime,
) -> int:
    doc_id = _next_id(con, "documents")
    con.execute(
        """INSERT INTO documents
           (id, filename, checksum, document_type, year, upload_timestamp, page_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [doc_id, filename, checksum, document_type, year, upload_timestamp, page_count],
    )
    return doc_id


def insert_tables(
    con: duckdb.DuckDBPyConnection, doc_id: int, sections: list[ExtractedSection]
) -> int:
    """Store one raw-table record per section (page = its first page)."""
    next_id = _next_id(con, "tables")
    rows = []
    for sec in sections:
        raw_json = json.dumps(
            [{"page": r.page, "cells": r.cells} for r in sec.rows],
            ensure_ascii=False,
        )
        rows.append((next_id, doc_id, sec.page_start, sec.table_type, raw_json))
        next_id += 1
    con.executemany(
        "INSERT INTO tables (id, document_id, page, table_type, raw_json) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def insert_metrics(
    con: duckdb.DuckDBPyConnection, doc_id: int, year: int, rows: list[NormalizedRow]
) -> int:
    """Insert one metric row per (line, year) for every row carrying a value.

    ``value_2024``/``value_2023`` are the current/prior columns; they map to the
    document's reporting ``year`` and ``year - 1``.
    """
    next_id = _next_id(con, "metrics")
    records = []
    for r in rows:
        for yr, value in ((year, r.value_2024), (year - 1, r.value_2023)):
            if value is None:
                continue
            records.append(
                (next_id, doc_id, yr, r.table_type, r.code or None,
                 r.description, value, "EUR", r.page)
            )
            next_id += 1
    con.executemany(
        """INSERT INTO metrics
           (id, document_id, year, category, code, metric_name, value, unit, source_page)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        records,
    )
    return len(records)


def insert_entities(
    con: duckdb.DuckDBPyConnection, doc_id: int, year: int, entities: list[Entity]
) -> int:
    """Insert consolidation-area entities for a document."""
    next_id = _next_id(con, "entities")
    records = []
    for e in entities:
        slug, canon = canonicalize(e.name)
        records.append(
            (next_id, doc_id, year, e.name, slug, canon, e.ownership_percentage,
             e.consolidation_method, e.entity_type, e.page)
        )
        next_id += 1
    con.executemany(
        """INSERT INTO entities
           (id, document_id, year, name, canonical_slug, canonical_name,
            ownership_percentage, consolidation_method, entity_type, source_page)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        records,
    )
    return len(records)


def insert_entity_metrics(
    con: duckdb.DuckDBPyConnection, doc_id: int, year: int, metrics: list[EntityMetric]
) -> int:
    """Insert long-format per-entity figures (personnel, valuation, ...)."""
    next_id = _next_id(con, "entity_metrics")
    records = []
    for m in metrics:
        slug, canon = canonicalize(m.entity_name)
        records.append(
            (next_id, doc_id, year, m.entity_name, slug, canon, m.source,
             m.metric_name, m.value, m.unit, m.note, m.page)
        )
        next_id += 1
    con.executemany(
        """INSERT INTO entity_metrics
           (id, document_id, year, entity_name, canonical_slug, canonical_name,
            source, metric_name, value, unit, note, source_page)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        records,
    )
    return len(records)


def insert_rendiconto(
    con: duckdb.DuckDBPyConnection, doc_id: int, year: int, items: list[RendicontoItem]
) -> int:
    """Insert long-format rendiconto (conto del bilancio) items."""
    next_id = _next_id(con, "rendiconto")
    records = []
    for it in items:
        records.append(
            (next_id, doc_id, year, it.kind, it.level, it.code or None,
             it.name, it.measure, it.value, "EUR", it.page)
        )
        next_id += 1
    con.executemany(
        """INSERT INTO rendiconto
           (id, document_id, year, kind, level, code, name, measure, value, unit, source_page)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        records,
    )
    return len(records)


def insert_rendiconto_capitoli(
    con: duckdb.DuckDBPyConnection, doc_id: int, year: int, items: list[CapitoloItem]
) -> int:
    """Insert long-format analytic per-capitolo items."""
    next_id = _next_id(con, "rendiconto_capitoli")
    records = []
    for it in items:
        records.append(
            (next_id, doc_id, year, it.kind, it.sezione,
             it.liv1_code, it.liv1_name, it.liv2_code, it.liv2_name,
             it.liv3_code, it.liv3_name, it.capitolo_code, it.denominazione,
             it.measure, it.value, "EUR", it.page)
        )
        next_id += 1
    con.executemany(
        """INSERT INTO rendiconto_capitoli
           (id, document_id, year, kind, sezione, liv1_code, liv1_name,
            liv2_code, liv2_name, liv3_code, liv3_name, capitolo_code,
            denominazione, measure, value, unit, source_page)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        records,
    )
    return len(records)


def replace_debito(con: duckdb.DuckDBPyConnection, items: list[DebitoItem]) -> int:
    """Replace the whole curated debt series (it is not document-scoped).

    Idempotent: clears the ``debito`` table and re-inserts, so re-running the
    loader after editing the curated figures yields a clean, deterministic state.
    """
    con.execute("DELETE FROM debito")
    records = [
        (i + 1, it.year, it.measure, it.value, it.unit, it.source)
        for i, it in enumerate(items)
    ]
    con.executemany(
        "INSERT INTO debito (id, year, measure, value, unit, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        records,
    )
    return len(records)


def insert_note_items(
    con: duckdb.DuckDBPyConnection, doc_id: int, year: int, items: list[NoteItem]
) -> int:
    """Insert long-format nota integrativa detail items."""
    next_id = _next_id(con, "note_items")
    records = []
    for it in items:
        records.append(
            (next_id, doc_id, year, it.page, it.table_index, it.heading or None,
             it.kind, it.voce, it.period, it.value, it.unit)
        )
        next_id += 1
    con.executemany(
        """INSERT INTO note_items
           (id, document_id, year, source_page, table_index, heading,
            kind, voce, period, value, unit)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        records,
    )
    return len(records)
