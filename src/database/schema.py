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

-- Analytic per-capitolo detail of the rendiconto (Conto di Bilancio D.Lgs 118
-- analitico). The leaf layer beneath the per-missione/per-titolo aggregates in
-- ``rendiconto``: a missione's capitoli sum to its total. Long-format: one row
-- per (capitolo x measure). Uniform 3-level tree + capitolo, semantics by kind:
--   spesa   : liv1=missione, liv2=programma, liv3=macroaggregato
--   entrata : liv1=titolo,   liv2=tipologia, liv3=categoria
-- Core measures reuse the aggregate names (previsioni / impegni|accertamenti /
-- pagamenti_totali|riscossioni_totali); plus residui, cassa, FPV, economie, etc.
CREATE TABLE IF NOT EXISTS rendiconto_capitoli (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents(id),
    year          INTEGER NOT NULL,
    kind          VARCHAR NOT NULL,          -- spesa | entrata
    sezione       VARCHAR,                   -- spese: titolo (correnti/conto capitale/...)
    liv1_code     VARCHAR NOT NULL,
    liv1_name     VARCHAR NOT NULL,
    liv2_code     VARCHAR,
    liv2_name     VARCHAR,
    liv3_code     VARCHAR,
    liv3_name     VARCHAR,
    capitolo_code VARCHAR NOT NULL,
    denominazione VARCHAR NOT NULL,
    measure       VARCHAR NOT NULL,
    value         DECIMAL(20, 2),
    unit          VARCHAR NOT NULL DEFAULT 'EUR',
    source_page   INTEGER NOT NULL
);

-- Indebtedness of the Comune di Torino (curated from the Relazioni del Collegio
-- dei revisori dei conti, 2018-2025). Standalone -- it is NOT extracted from a
-- registered PDF, so it has no document_id FK; the source relazione is recorded
-- per row instead. Long-format: one row per (year x measure).
--   measure  residuo_iniziale | nuovi_prestiti | prestiti_rimborsati |
--            debito_fine_anno | oneri_finanziari | abitanti | debito_pro_capite
--   unit     EUR | ABITANTI | EUR_AB
CREATE TABLE IF NOT EXISTS debito (
    id       INTEGER PRIMARY KEY,
    year     INTEGER NOT NULL,
    measure  VARCHAR NOT NULL,
    value    DECIMAL(20, 2),
    unit     VARCHAR NOT NULL DEFAULT 'EUR',
    source   VARCHAR NOT NULL
);

-- Rendiconto della gestione (summary, per-missione/per-titolo) of OTHER comuni,
-- for cross-city comparison (the 14 città metropolitane). Sourced in bulk from the
-- BDAP/RGS per-region open-data ZIPs, so — like ``debito`` — it is standalone (no
-- document_id FK; the source ZIP/year is recorded per row). Same long-format and
-- measures as ``rendiconto``, plus a ``comune``/``region`` dimension. The Comune di
-- Torino is included here too, so the comparison reads a single uniform table.
--   comune   "TORINO" | "MILANO" | ...  (BDAP "Descrizione Comune", uppercase)
--   region   "PIEMONTE" | "LOMBARDIA" | ...
CREATE TABLE IF NOT EXISTS rendiconto_comuni (
    id       INTEGER PRIMARY KEY,
    comune   VARCHAR NOT NULL,
    region   VARCHAR NOT NULL,
    year     INTEGER NOT NULL,
    kind     VARCHAR NOT NULL,
    level    VARCHAR NOT NULL,
    code     VARCHAR,
    name     VARCHAR NOT NULL,
    measure  VARCHAR NOT NULL,
    value    DECIMAL(20, 2),
    unit     VARCHAR NOT NULL DEFAULT 'EUR',
    source   VARCHAR NOT NULL
);

-- Resident-population series (anagrafe, residenti al 31/12), used to express the
-- rendiconto figures in euro per abitante. Standalone curated data (like debito):
-- the source is recorded per row. Keyed by (comune, year) so other comuni can be
-- added later for a per-capita comparison; currently only Torino is loaded.
CREATE TABLE IF NOT EXISTS popolazione (
    comune    VARCHAR NOT NULL DEFAULT 'TORINO',
    year      INTEGER NOT NULL,
    residenti INTEGER NOT NULL,
    source    VARCHAR NOT NULL,
    PRIMARY KEY (comune, year)
);

-- Civil-code financial statements (stato patrimoniale + conto economico, schemi
-- ex artt. 2424/2425 c.c.) of the most important partecipate, parsed from each
-- società's deposited *fascicolo di bilancio* (uploads/partecipate/). Standalone
-- like ``debito``: not part of the consolidato ingest, so no document_id FK; the
-- source PDF + page are recorded per row. Long-format: one row per (voce x year),
-- with both the current and prior year of each fascicolo.
--   entity_slug  reuses the consolidato canonical slug (e.g. "infratrasporti_to")
--   category     'stato_patrimoniale_attivo' | 'stato_patrimoniale_passivo' |
--                'conto_economico'
--   code         leading schema code ("A.I.", "11)", "") -- "" for totals/results
--   is_total     the line is a (sub)total / result row
--   related_party 'socio' (verso/da controllanti = Città di Torino) | 'gruppo_socio'
--                (imprese sottoposte al controllo delle controllanti) | 'controllate'
CREATE TABLE IF NOT EXISTS entity_statements (
    id            INTEGER PRIMARY KEY,
    entity_slug   VARCHAR NOT NULL,
    entity_name   VARCHAR NOT NULL,
    year          INTEGER NOT NULL,
    category      VARCHAR NOT NULL,
    seq           INTEGER NOT NULL,   -- printed order within (category, year)
    code          VARCHAR,
    name          VARCHAR NOT NULL,
    value         DECIMAL(20, 2),
    unit          VARCHAR NOT NULL DEFAULT 'EUR',
    is_total      BOOLEAN NOT NULL DEFAULT FALSE,
    related_party VARCHAR,
    source_document VARCHAR NOT NULL,
    source_page   INTEGER NOT NULL
);

-- Public contracts (appalti/affidamenti) from the Comune's L.190/2012 art.1 c.32
-- open dataset (one row per lotto per reference year). The CIG is the join key to
-- ANAC; capitolo_code is the (optional) bridge to the budget, populated from the
-- determinazione dirigenziale where known.
CREATE TABLE IF NOT EXISTS contratti (
    id                  INTEGER PRIMARY KEY,
    cig                 VARCHAR,
    anno                INTEGER NOT NULL,   -- dataset reference year
    oggetto             VARCHAR,
    struttura           VARCHAR,            -- struttura proponente
    scelta_contraente   VARCHAR,            -- procedura (es. 23-AFFIDAMENTO DIRETTO)
    aggiudicatario      VARCHAR,
    aggiudicatario_cf   VARCHAR,
    n_partecipanti      INTEGER,
    importo_aggiudicazione DECIMAL(20, 2),
    importo_liquidato   DECIMAL(20, 2),     -- somme liquidate nell'anno
    data_inizio         VARCHAR,
    data_ultimazione    VARCHAR,
    capitolo_code       VARCHAR,            -- bridge to rendiconto_capitoli (via DD)
    source_document     VARCHAR NOT NULL
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
