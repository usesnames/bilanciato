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

    def _has_table(self, name: str) -> bool:
        """Whether a table exists. Lets newer code degrade gracefully against an
        older database (e.g. a deployed DB that lags the deployed code)."""
        return self._one(
            "SELECT 1 AS x FROM information_schema.tables WHERE table_name = ?", [name]
        ) is not None

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
        """Distinct canonical entities across all years (for the explorer index).

        Unions the GAP directory (``entities``, the Comune's *direct*
        participations) with the consolidation-perimeter entities that appear
        only in ``entity_metrics`` (personale/valutazione). The latter includes
        intermediary holdings such as FCT Holding — which controls GTT — that
        are not direct participations and so are absent from the GAP table, but
        the user still expects to find in the explorer.
        """
        return self._rows(
            """WITH all_ent AS (
                   SELECT canonical_slug, canonical_name, entity_type, year
                   FROM entities WHERE canonical_slug IS NOT NULL
                   UNION ALL
                   SELECT canonical_slug, canonical_name, NULL AS entity_type, year
                   FROM entity_metrics WHERE canonical_slug IS NOT NULL
                   UNION ALL
                   SELECT entity_slug AS canonical_slug, entity_name AS canonical_name,
                          NULL AS entity_type, year
                   FROM entity_statements
               )
               SELECT canonical_slug,
                      max(canonical_name) AS canonical_name,
                      max(entity_type) AS entity_type,
                      min(year) AS first_year, max(year) AS last_year,
                      count(DISTINCT year) AS n_years
               FROM all_ent
               GROUP BY canonical_slug
               ORDER BY canonical_name"""
        )

    # -- partecipate civil-code statements (SP + CE) ------------------------
    def entity_statement_years(self, slug: str) -> list[int]:
        """Years for which a fascicolo statement is loaded for this entity."""
        return [r["year"] for r in self._rows(
            "SELECT DISTINCT year FROM entity_statements WHERE entity_slug = ? "
            "ORDER BY year DESC", [slug])]

    def entity_statements(self, slug: str, *, category: str | None = None,
                          years: list[int] | None = None) -> list[dict[str, Any]]:
        """The civil-code statement rows of a partecipata, in printed order.

        Long-format (one row per voce x year); the dashboard pivots the years
        side by side. Optionally filtered to a category and/or a set of years.
        """
        where = ["entity_slug = ?"]
        params: list[Any] = [slug]
        if category is not None:
            where.append("category = ?")
            params.append(category)
        if years:
            where.append(f"year IN ({', '.join('?' * len(years))})")
            params.extend(years)
        return self._rows(
            f"""SELECT entity_slug, entity_name, year, category, seq, code, name,
                       value, unit, is_total, related_party,
                       source_document, source_page
                FROM entity_statements
                WHERE {' AND '.join(where)}
                ORDER BY category, seq, year DESC""",
            params,
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

    # -- cross-city comparison (città metropolitane, from BDAP) -------------
    def confronto_cities(self) -> list[dict[str, Any]]:
        """The comuni available for comparison, with their year span."""
        return self._rows(
            """SELECT comune, region, min(year) AS first_year, max(year) AS last_year,
                      count(DISTINCT year) AS n_years
               FROM rendiconto_comuni
               GROUP BY comune, region
               ORDER BY comune"""
        )

    def confronto_rendiconto(
        self, *, comune: str, kind: str, measure: str, year: int | None = None,
        level: str = "voce",
    ) -> list[dict[str, Any]]:
        """One comparison comune's rendiconto rows (per-voce by default) for a
        kind/measure — same missione/titolo breakdown as the Torino ``rendiconto``."""
        params: list[Any] = [comune, kind, measure, level]
        yr = ""
        if year is not None:
            yr = "AND year = ?"
            params.append(year)
        return self._rows(
            f"""SELECT comune, region, year, kind, level, code, name, measure, value, source
                FROM rendiconto_comuni
                WHERE comune = ? AND kind = ? AND measure = ? AND level = ? {yr}
                ORDER BY year, code""",
            params,
        )

    def all_rendiconto_comuni(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT comune, region, year, kind, level, code, name, measure,
                      value, unit, source
               FROM rendiconto_comuni
               ORDER BY comune, year DESC, kind, measure, code NULLS LAST"""
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

    # -- popolazione (resident series, for euro per-capita) -----------------
    def popolazione(self, comune: str = "TORINO") -> list[dict[str, Any]]:
        return self._rows(
            "SELECT comune, year, residenti, source FROM popolazione "
            "WHERE comune = ? ORDER BY year",
            [comune],
        )

    def popolazione_all(self) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT comune, year, residenti, source FROM popolazione "
            "ORDER BY comune, year"
        )

    def all_entity_statements(self) -> list[dict[str, Any]]:
        """Every partecipata civil-code statement row (for the open-data export)."""
        return self._rows(
            """SELECT entity_slug, entity_name, year, category, seq, code, name,
                      value, unit, is_total, related_party,
                      source_document, source_page
               FROM entity_statements
               ORDER BY entity_slug, category, seq, year DESC"""
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
        if not self._has_table("rendiconto_capitoli"):
            return []
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

    def capitoli_timeseries(
        self, *, kind: str, measure: str, capitolo_code: str | None = None,
        liv1: str | None = None, liv2: str | None = None, liv3: str | None = None,
    ) -> list[dict[str, Any]]:
        """One value per year for a single capitolo or an aggregated level
        (filter by capitolo_code, or by liv1/liv2/liv3), for one measure."""
        where = ["kind = ?", "measure = ?"]
        params: list[Any] = [kind, measure]
        for col, val in (("capitolo_code", capitolo_code), ("liv1_code", liv1),
                         ("liv2_code", liv2), ("liv3_code", liv3)):
            if val is not None:
                where.append(f"{col} = ?")
                params.append(val)
        return self._rows(
            f"""SELECT year, sum(value) AS value, max(denominazione) AS denominazione
                FROM rendiconto_capitoli WHERE {' AND '.join(where)}
                GROUP BY year ORDER BY year""",
            params,
        )

    def capitoli_distinct(
        self, *, kind: str, liv1: str, liv2: str | None = None, level: str = "capitolo",
    ) -> list[dict[str, Any]]:
        """Distinct items (across all years) for the trend selector, within a
        missione/titolo (optionally a programma/tipologia). ``level`` is
        'capitolo' or 'liv3' (macroaggregato/categoria)."""
        where = ["kind = ?", "liv1_code = ?"]
        params: list[Any] = [kind, liv1]
        if liv2 is not None:
            where.append("liv2_code = ?")
            params.append(liv2)
        if level == "liv3":
            return self._rows(
                f"""SELECT liv3_code AS code, max(liv3_name) AS name
                    FROM rendiconto_capitoli
                    WHERE {' AND '.join(where)} AND liv3_code IS NOT NULL
                    GROUP BY liv3_code ORDER BY max(liv3_name)""",
                params,
            )
        return self._rows(
            f"""SELECT capitolo_code AS code, max(denominazione) AS name
                FROM rendiconto_capitoli WHERE {' AND '.join(where)}
                GROUP BY capitolo_code ORDER BY max(denominazione)""",
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

    # -- contratti / appalti (L.190 open data) ------------------------------
    def contratti_years(self) -> list[int]:
        if not self._has_table("contratti"):
            return []
        return [int(r["anno"]) for r in
                self._rows("SELECT DISTINCT anno FROM contratti ORDER BY anno")]

    def contratti(
        self, *, anno: int | None = None, search: str | None = None,
        order_by: str = "importo_aggiudicazione", limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Contracts, ranked (default by award amount), optionally filtered by year
        and a free-text match on oggetto/aggiudicatario."""
        col = "importo_aggiudicazione" if order_by not in (
            "importo_aggiudicazione", "importo_liquidato") else order_by
        where, params = [], []
        if anno is not None:
            where.append("anno = ?")
            params.append(anno)
        if search:
            where.append("(oggetto ILIKE ? OR aggiudicatario ILIKE ? OR cig ILIKE ?)")
            params += [f"%{search}%"] * 3
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)
        return self._rows(
            f"""SELECT cig, anno, oggetto, struttura, scelta_contraente, aggiudicatario,
                       n_partecipanti, importo_aggiudicazione, importo_liquidato,
                       data_inizio, data_ultimazione, capitolo_code
                FROM contratti {clause}
                ORDER BY {col} DESC NULLS LAST LIMIT ?""",
            params,
        )

    def contratti_summary(self, *, anno: int | None = None) -> dict[str, Any]:
        """Headline totals for the contracts page."""
        where = "WHERE anno = ?" if anno is not None else ""
        params = [anno] if anno is not None else []
        r = self._rows(
            f"""SELECT count(*) AS n,
                       sum(importo_aggiudicazione) AS tot_aggiudicato,
                       sum(importo_liquidato) AS tot_liquidato,
                       count(DISTINCT aggiudicatario) AS n_fornitori
                FROM contratti {where}""",
            params,
        )
        return r[0] if r else {}

    def contratti_top_fornitori(
        self, *, anno: int | None = None, limit: int = 15,
    ) -> list[dict[str, Any]]:
        where = "WHERE anno = ?" if anno is not None else ""
        params = [anno] if anno is not None else []
        params.append(limit)
        return self._rows(
            f"""SELECT aggiudicatario,
                       count(*) AS n_contratti,
                       sum(importo_aggiudicazione) AS importo
                FROM contratti {where}
                GROUP BY aggiudicatario
                ORDER BY importo DESC NULLS LAST LIMIT ?""",
            params,
        )

    def all_contratti(self) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT cig, anno, oggetto, struttura, scelta_contraente, aggiudicatario,
                      aggiudicatario_cf, n_partecipanti, importo_aggiudicazione,
                      importo_liquidato, data_inizio, data_ultimazione, capitolo_code,
                      source_document
               FROM contratti ORDER BY anno, importo_aggiudicazione DESC NULLS LAST"""
        )
