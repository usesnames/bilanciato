"""DuckDB schema and connection.

Canonical schema per CLAUDE.md, with two pragmatic additions kept faithful to the
spirit of the design:

* ``metrics.code`` -- the statement hierarchy path (e.g. ``II.1``), which is what
  makes a value navigable back to its line in the printed schema;
* ``metrics`` stores one row per (metric, year): each printed line carries both a
  2024 and a 2023 figure, and the ``year`` column already distinguishes them.

The schema is idempotent: ingesting re-creates a clean database deterministically.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from src.utils.config import DB_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY,
    filename        VARCHAR NOT NULL,
    checksum        VARCHAR NOT NULL,
    document_type   VARCHAR NOT NULL,
    year            INTEGER NOT NULL,
    upload_timestamp TIMESTAMP NOT NULL,
    page_count      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tables (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    page        INTEGER NOT NULL,
    table_type  VARCHAR NOT NULL,
    raw_json    VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    year        INTEGER NOT NULL,
    category    VARCHAR NOT NULL,   -- statement type (income_statement, ...)
    code        VARCHAR,            -- hierarchy path within the statement
    metric_name VARCHAR NOT NULL,
    value       DECIMAL(20, 2),
    unit        VARCHAR NOT NULL DEFAULT 'EUR',
    source_page INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id                   INTEGER PRIMARY KEY,
    document_id          INTEGER NOT NULL REFERENCES documents(id),
    year                 INTEGER NOT NULL,
    name                 VARCHAR NOT NULL,
    canonical_slug       VARCHAR,   -- stable cross-source key (see entity_names.py)
    canonical_name       VARCHAR,
    ownership_percentage DECIMAL(7, 4),
    consolidation_method VARCHAR,
    entity_type          VARCHAR,
    source_page          INTEGER
);

-- Long-format per-entity figures from the nota integrativa (personnel costs,
-- participation valuation / net equity, ...). One row per entity x figure.
CREATE TABLE IF NOT EXISTS entity_metrics (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    year        INTEGER NOT NULL,
    entity_name VARCHAR NOT NULL,
    canonical_slug VARCHAR,         -- stable cross-source key (see entity_names.py)
    canonical_name VARCHAR,
    source      VARCHAR NOT NULL,   -- personale | valutazione_diretta | valutazione_indiretta
    metric_name VARCHAR NOT NULL,
    value       DECIMAL(20, 4),
    unit        VARCHAR NOT NULL,   -- EUR | PCT
    note        VARCHAR,            -- e.g. elimination entry id
    source_page INTEGER NOT NULL
);

-- Long-format nota integrativa detail tables (movimenti / confronto / dettaglio).
-- One row per voce x period.
CREATE TABLE IF NOT EXISTS note_items (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    year        INTEGER NOT NULL,
    source_page INTEGER NOT NULL,
    table_index INTEGER NOT NULL,
    heading     VARCHAR,            -- nota integrativa section heading on the page
    kind        VARCHAR NOT NULL,   -- movimenti | confronto | dettaglio
    voce        VARCHAR NOT NULL,
    period      VARCHAR NOT NULL,   -- inizio|variazione|fine | 2023|2024
    value       DECIMAL(20, 2),
    unit        VARCHAR NOT NULL DEFAULT 'EUR'
);

-- Rendiconto della gestione (conto del bilancio) of the Comune di Torino alone,
-- on a financial (cassa/competenza) basis -- distinct from the accrual bilancio
-- consolidato of the whole group. Long-format: one row per (record x measure).
--   kind    'spesa' | 'entrata'
--   level   'voce'  (a missione/titolo) | 'totale' (grand total)
--   code    missione '01'..'99' / titolo '1'..'9'; NULL for the grand total
--   measure 'previsioni' | 'impegni' | 'pagamenti_totali'        (spese)
--           'previsioni' | 'accertamenti' | 'riscossioni_totali' (entrate)
CREATE TABLE IF NOT EXISTS rendiconto (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    year        INTEGER NOT NULL,
    kind        VARCHAR NOT NULL,
    level       VARCHAR NOT NULL,
    code        VARCHAR,
    name        VARCHAR NOT NULL,
    measure     VARCHAR NOT NULL,
    value       DECIMAL(20, 2),
    unit        VARCHAR NOT NULL DEFAULT 'EUR',
    source_page INTEGER NOT NULL
);

-- The entity-name crosswalk: every raw name seen in any source mapped to its
-- canonical slug/name. This is the "normalization map" as a queryable object.
CREATE OR REPLACE VIEW entity_crosswalk AS
    SELECT DISTINCT name AS raw_name, 'entities' AS source, canonical_slug, canonical_name
    FROM entities
    UNION
    SELECT DISTINCT entity_name AS raw_name, source, canonical_slug, canonical_name
    FROM entity_metrics;
"""


def connect(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (creating the parent dir if needed) the project DuckDB database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create all canonical tables if they do not yet exist."""
    con.execute(SCHEMA_SQL)
