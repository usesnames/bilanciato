"""Read-only data-access layer over the project DuckDB.

Shared by the Streamlit dashboard (interactive, human-facing) and the static
publisher (``src/publish``, which renders the LLM-readable data site). Nothing here
writes: ingestion (``src/etl``) is the only writer.

The connection is opened read-only and each query runs on a fresh cursor, so the
layer is safe to use from Streamlit's script threads (a single DuckDB connection is
not thread-safe to share, but ``connection.cursor()`` gives an isolated executor).

Every query that returns a financial value also returns its provenance
(``source_document`` + ``source_page``), because CLAUDE.md requires every value to
remain traceable back to a PDF page.
"""

from __future__ import annotations

import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from src.utils.config import DB_PATH


def _jsonable(value: Any) -> Any:
    """Make DuckDB scalar values JSON/pydantic-friendly (Decimal -> float)."""
    if isinstance(value, Decimal):
        return float(value)
    return value


class Repository:
    """Thin, read-only query surface over the bilanciaTo DuckDB."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        if not db_path.exists():
            raise FileNotFoundError(
                f"database not found at {db_path}; run `python -m src.etl.ingest` first"
            )
        self.db_path = db_path
        # One shared read-only connection; per-query cursors for thread-safety.
        self._con = duckdb.connect(str(db_path), read_only=True)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._con.close()

    # -- low-level helpers --------------------------------------------------
    def _rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Run a query and return a list of dicts with JSON-friendly scalars."""
        # cursor() is cheap and gives an isolated execution context per call.
        with self._lock:
            cur = self._con.cursor()
            cur.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            data = cur.fetchall()
        return [{c: _jsonable(v) for c, v in zip(cols, row)} for row in data]

    def _one(self, sql: str, params: list[Any] | None = None) -> dict[str, Any] | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    # -- documents ----------------------------------------------------------
    def documents(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT id, filename, document_type, year, page_count,
                      checksum, upload_timestamp
               FROM documents ORDER BY year DESC"""
        )

    def document(self, doc_id: int) -> dict[str, Any] | None:
        return self._one(
            """SELECT id, filename, document_type, year, page_count,
                      checksum, upload_timestamp
               FROM documents WHERE id = ?""",
            [doc_id],
        )

    # -- years --------------------------------------------------------------
    def years(self) -> list[int]:
        rows = self._rows("SELECT DISTINCT year FROM metrics ORDER BY year")
        return [int(r["year"]) for r in rows]

    # -- metrics ------------------------------------------------------------
    def metric_categories(self) -> list[str]:
        rows = self._rows("SELECT DISTINCT category FROM metrics ORDER BY category")
        return [r["category"] for r in rows]

    def metrics(
        self,
        *,
        year: int | None = None,
        category: str | None = None,
        code: str | None = None,
        query: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Filtered metric lines, each with its source document + page."""
        where: list[str] = []
        params: list[Any] = []
        if year is not None:
            where.append("m.year = ?")
            params.append(year)
        if category is not None:
            where.append("m.category = ?")
            params.append(category)
        if code is not None:
            where.append("m.code = ?")
            params.append(code)
        if query:
            where.append("lower(m.metric_name) LIKE ?")
            params.append(f"%{query.lower()}%")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.extend([limit, offset])
        return self._rows(
            f"""SELECT m.id, m.year, m.category, m.code, m.metric_name,
                       m.value, m.unit, m.source_page,
                       d.id AS document_id, d.filename AS source_document
                FROM metrics m JOIN documents d ON d.id = m.document_id
                {clause}
                ORDER BY m.year DESC, m.category, m.id
                LIMIT ? OFFSET ?""",
            params,
        )

    def metric_timeseries(self, metric_name: str, category: str | None = None) -> list[dict[str, Any]]:
        """All years for a metric name (case-insensitive exact match), with provenance.

        Prefers, per year, the value from the document whose reporting year matches
        (the authoritative current-year figure) over a prior-year restatement.
        """
        params: list[Any] = [metric_name.lower()]
        cat = ""
        if category is not None:
            cat = "AND m.category = ?"
            params.append(category)
        return self._rows(
            f"""WITH ranked AS (
                    SELECT m.year, m.category, m.code, m.metric_name, m.value, m.unit,
                           m.source_page, d.filename AS source_document, d.year AS doc_year,
                           row_number() OVER (
                               PARTITION BY m.year, m.category
                               ORDER BY CASE WHEN d.year = m.year THEN 0 ELSE 1 END,
                                        d.year DESC
                           ) AS rk
                    FROM metrics m JOIN documents d ON d.id = m.document_id
                    WHERE lower(m.metric_name) = ? {cat}
                )
                SELECT year, category, code, metric_name, value, unit,
                       source_page, source_document
                FROM ranked WHERE rk = 1 ORDER BY year""",
            params,
        )

    # -- entities -----------------------------------------------------------
    def entities(self, *, year: int | None = None, slug: str | None = None) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if year is not None:
            where.append("e.year = ?")
            params.append(year)
        if slug is not None:
            where.append("e.canonical_slug = ?")
            params.append(slug)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        return self._rows(
            f"""SELECT e.id, e.year, e.name, e.canonical_slug, e.canonical_name,
                       e.ownership_percentage, e.consolidation_method, e.entity_type,
                       e.source_page, d.filename AS source_document
                FROM entities e JOIN documents d ON d.id = e.document_id
                {clause}
                ORDER BY e.year DESC, e.canonical_name""",
            params,
        )

    def entity_metrics(self, slug: str, *, year: int | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [slug]
        yr = ""
        if year is not None:
            yr = "AND em.year = ?"
            params.append(year)
        return self._rows(
            f"""SELECT em.year, em.entity_name, em.canonical_slug, em.canonical_name,
                       em.source, em.metric_name, em.value, em.unit, em.note,
                       em.source_page, d.filename AS source_document
                FROM entity_metrics em JOIN documents d ON d.id = em.document_id
                WHERE em.canonical_slug = ? {yr}
                ORDER BY em.year DESC, em.source, em.metric_name""",
            params,
        )

    def entity_metric_timeseries(self, slug: str, metric_name: str) -> list[dict[str, Any]]:
        """One entity's values for one metric across years, with provenance.

        Each entity_metrics row is tagged with its document's reporting year and
        profiles don't overlap, so there is exactly one value per year.
        """
        return self._rows(
            """SELECT em.year, em.value, em.unit, em.canonical_name, em.source,
                      em.source_page, d.filename AS source_document
               FROM entity_metrics em JOIN documents d ON d.id = em.document_id
               WHERE em.canonical_slug = ? AND em.metric_name = ?
               ORDER BY em.year""",
            [slug, metric_name],
        )

    def entity_metrics_multiyear(self, slug: str) -> list[str]:
        """Metric names this entity has for at least two distinct years."""
        rows = self._rows(
            """SELECT metric_name
               FROM entity_metrics
               WHERE canonical_slug = ?
               GROUP BY metric_name
               HAVING count(DISTINCT year) >= 2
               ORDER BY metric_name""",
            [slug],
        )
        return [r["metric_name"] for r in rows]

    def entities_with_metric(self, metric_name: str) -> list[dict[str, Any]]:
        """Distinct entities that report a given metric (for cross-entity compare)."""
        return self._rows(
            """SELECT canonical_slug, canonical_name, count(DISTINCT year) AS n_years
               FROM entity_metrics
               WHERE metric_name = ? AND canonical_slug IS NOT NULL
               GROUP BY canonical_slug, canonical_name
               ORDER BY canonical_name""",
            [metric_name],
        )

    def entity_directory(self) -> list[dict[str, Any]]:
        """Distinct canonical entities across all years (for the explorer index)."""
        return self._rows(
            """SELECT canonical_slug, canonical_name,
                      max(entity_type) AS entity_type,
                      min(year) AS first_year, max(year) AS last_year,
                      count(DISTINCT year) AS n_years
               FROM entities
               WHERE canonical_slug IS NOT NULL
               GROUP BY canonical_slug, canonical_name
               ORDER BY canonical_name"""
        )

    # -- rendiconto della gestione ------------------------------------------
    def rendiconto_years(self) -> list[int]:
        rows = self._rows("SELECT DISTINCT year FROM rendiconto ORDER BY year")
        return [int(r["year"]) for r in rows]

    def rendiconto(
        self, *, kind: str, measure: str, year: int | None = None, level: str = "voce"
    ) -> list[dict[str, Any]]:
        """Rendiconto rows for one kind/measure (per-voce by default), with provenance."""
        params: list[Any] = [kind, measure, level]
        yr = ""
        if year is not None:
            yr = "AND r.year = ?"
            params.append(year)
        return self._rows(
            f"""SELECT r.year, r.kind, r.level, r.code, r.name, r.measure, r.value,
                       r.unit, r.source_page, d.filename AS source_document
                FROM rendiconto r JOIN documents d ON d.id = r.document_id
                WHERE r.kind = ? AND r.measure = ? AND r.level = ? {yr}
                ORDER BY r.year, r.code""",
            params,
        )

    def rendiconto_measures(self, kind: str) -> list[str]:
        rows = self._rows(
            "SELECT DISTINCT measure FROM rendiconto WHERE kind = ? ORDER BY measure",
            [kind],
        )
        return [r["measure"] for r in rows]

    def rendiconto_total(self, *, kind: str, measure: str, year: int) -> dict[str, Any] | None:
        """The printed grand total for one kind/measure/year (with provenance)."""
        return self._one(
            """SELECT r.year, r.value, r.source_page, d.filename AS source_document
               FROM rendiconto r JOIN documents d ON d.id = r.document_id
               WHERE r.kind = ? AND r.measure = ? AND r.level = 'totale' AND r.year = ?""",
            [kind, measure, year],
        )

    # -- search -------------------------------------------------------------
    def search(self, query: str, limit: int = 50) -> dict[str, list[dict[str, Any]]]:
        """Free-text search across metric names, entity names and note voci."""
        like = f"%{query.lower()}%"
        metrics = self._rows(
            """SELECT m.year, m.category, m.code, m.metric_name, m.value, m.unit,
                      m.source_page, d.filename AS source_document
               FROM metrics m JOIN documents d ON d.id = m.document_id
               WHERE lower(m.metric_name) LIKE ?
               ORDER BY m.year DESC, m.metric_name LIMIT ?""",
            [like, limit],
        )
        # Search both the consolidation list and the valuation/personnel figures:
        # some names (e.g. SMAT, valued at equity) appear only in entity_metrics.
        entities = self._rows(
            """SELECT canonical_slug, canonical_name,
                      max(entity_type) AS entity_type
               FROM (
                   SELECT canonical_slug, canonical_name, entity_type, name AS raw
                   FROM entities
                   UNION ALL
                   SELECT canonical_slug, canonical_name, NULL AS entity_type,
                          entity_name AS raw
                   FROM entity_metrics
               )
               WHERE canonical_slug IS NOT NULL
                 AND (lower(raw) LIKE ? OR lower(canonical_name) LIKE ?)
               GROUP BY canonical_slug, canonical_name
               ORDER BY canonical_name LIMIT ?""",
            [like, like, limit],
        )
        notes = self._rows(
            """SELECT ni.year, ni.heading, ni.kind, ni.voce, ni.period, ni.value,
                      ni.unit, ni.source_page, d.filename AS source_document
               FROM note_items ni JOIN documents d ON d.id = ni.document_id
               WHERE lower(ni.voce) LIKE ?
               ORDER BY ni.year DESC, ni.voce LIMIT ?""",
            [like, limit],
        )
        return {"metrics": metrics, "entities": entities, "notes": notes}

    # -- full exports (used by the static publisher) ------------------------
    def all_metrics(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT m.id, m.year, m.category, m.code, m.metric_name, m.value,
                      m.unit, m.source_page, d.filename AS source_document
               FROM metrics m JOIN documents d ON d.id = m.document_id
               ORDER BY m.year DESC, m.category, m.code NULLS LAST, m.metric_name"""
        )

    def all_entities(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT e.year, e.name, e.canonical_slug, e.canonical_name,
                      e.ownership_percentage, e.consolidation_method, e.entity_type,
                      e.source_page, d.filename AS source_document
               FROM entities e JOIN documents d ON d.id = e.document_id
               ORDER BY e.year DESC, e.canonical_name"""
        )

    def all_entity_metrics(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT em.year, em.entity_name, em.canonical_slug, em.canonical_name,
                      em.source, em.metric_name, em.value, em.unit, em.note,
                      em.source_page, d.filename AS source_document
               FROM entity_metrics em JOIN documents d ON d.id = em.document_id
               ORDER BY em.year DESC, em.canonical_name, em.source, em.metric_name"""
        )

    def all_rendiconto(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT r.year, r.kind, r.level, r.code, r.name, r.measure, r.value,
                      r.unit, r.source_page, d.filename AS source_document
               FROM rendiconto r JOIN documents d ON d.id = r.document_id
               ORDER BY r.year DESC, r.kind, r.measure, r.code NULLS LAST"""
        )

    def all_note_items(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT ni.year, ni.source_page, ni.table_index, ni.heading, ni.kind,
                      ni.voce, ni.period, ni.value, ni.unit,
                      d.filename AS source_document
               FROM note_items ni JOIN documents d ON d.id = ni.document_id
               ORDER BY ni.year DESC, ni.source_page, ni.table_index"""
        )

    # -- debito (curated municipal-debt series) -----------------------------
    def debito_years(self) -> list[int]:
        rows = self._rows("SELECT DISTINCT year FROM debito ORDER BY year")
        return [int(r["year"]) for r in rows]

    def debito_measures(self) -> list[str]:
        rows = self._rows("SELECT DISTINCT measure FROM debito")
        return [r["measure"] for r in rows]

    def debito(self, measure: str | None = None) -> list[dict[str, Any]]:
        """Debt rows (optionally one measure), each carrying its source relazione."""
        where, params = "", []
        if measure is not None:
            where = "WHERE measure = ?"
            params.append(measure)
        return self._rows(
            f"""SELECT year, measure, value, unit, source
                FROM debito {where} ORDER BY year, measure""",
            params,
        )

    def all_debito(self) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT year, measure, value, unit, source FROM debito "
            "ORDER BY year, measure"
        )

    # -- rendiconto per capitoli (analytic detail) --------------------------
    def capitoli_years(self) -> list[int]:
        rows = self._rows("SELECT DISTINCT year FROM rendiconto_capitoli ORDER BY year")
        return [int(r["year"]) for r in rows]

    def capitoli_tree(self, *, kind: str, year: int, measure: str) -> list[dict[str, Any]]:
        """Aggregated liv1->liv2->liv3 sums for one kind/year/measure (treemap)."""
        return self._rows(
            """SELECT liv1_code, liv1_name, liv2_code, liv2_name,
                      liv3_code, liv3_name, sum(value) AS value
               FROM rendiconto_capitoli
               WHERE kind = ? AND year = ? AND measure = ?
               GROUP BY liv1_code, liv1_name, liv2_code, liv2_name, liv3_code, liv3_name""",
            [kind, year, measure],
        )

    def capitoli_liv1(self, *, kind: str, year: int) -> list[dict[str, Any]]:
        """Distinct top-level voci (missione/titolo) for the drill-down selector."""
        return self._rows(
            """SELECT DISTINCT liv1_code, liv1_name FROM rendiconto_capitoli
               WHERE kind = ? AND year = ? ORDER BY liv1_code""",
            [kind, year],
        )

    def capitoli(
        self, *, kind: str, year: int, measure: str,
        liv1: str | None = None, liv2: str | None = None, limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """Single capitoli (optionally within a missione/titolo and programma),
        ranked by value, each with its hierarchy and source page."""
        where = ["kind = ?", "year = ?", "measure = ?"]
        params: list[Any] = [kind, year, measure]
        if liv1 is not None:
            where.append("liv1_code = ?")
            params.append(liv1)
        if liv2 is not None:
            where.append("liv2_code = ?")
            params.append(liv2)
        params.append(limit)
        return self._rows(
            f"""SELECT liv1_code, liv1_name, liv2_code, liv2_name, liv3_code, liv3_name,
                       capitolo_code, denominazione, value, source_page, sezione
                FROM rendiconto_capitoli
                WHERE {' AND '.join(where)}
                ORDER BY value DESC LIMIT ?""",
            params,
        )

    def all_capitoli(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT year, kind, sezione, liv1_code, liv1_name, liv2_code, liv2_name,
                      liv3_code, liv3_name, capitolo_code, denominazione,
                      measure, value, unit, source_page
               FROM rendiconto_capitoli
               ORDER BY year, kind, liv1_code, liv2_code, liv3_code, capitolo_code, measure"""
        )
