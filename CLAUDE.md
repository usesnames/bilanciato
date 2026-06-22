# CLAUDE.md

# bilanciaTo

bilanciaTo is an open-source platform for extracting, structuring, exploring and querying the consolidated financial statements of the City of Turin (Comune di Torino).

The project transforms uploaded PDF financial reports into a structured analytical database that can be explored by both humans and LLMs.

The system must prioritize:

1. transparency
2. traceability
3. reproducibility
4. machine readability
5. financial correctness

The project name intentionally combines:

* Bilancio
* Torino
* Data

---

# Project Goal

A user uploads one or more official PDF financial reports.

The system automatically:

1. extracts tables using pdfplumber
2. normalizes the extracted data
3. stores the data in DuckDB
4. generates an interactive dashboard for humans
5. publishes a static, LLM-readable data site for grounded AI querying

Grounded LLM querying does NOT mean a built-in chatbot. Instead the project
publishes the structured data as a static website (HTML + JSON/CSV + `llms.txt`)
that any external model (Claude, ChatGPT, ...) can be pointed at: a user tells
their assistant to read the bilanciaTo data site and answer a question, and the
model grounds its answer on the published figures, each of which carries its
source document and PDF page. No proprietary API endpoint and no API keys are
operated by this project.

---

# Non Goals

The system must NOT:

* manually edit extracted values
* rely on model memory for financial answers
* depend on external websites
* require manual table transcription
* operate its own LLM API endpoint or hold model API keys
  (LLM access is via the published static data site, consumed by the user's own assistant)

---

# Guiding Principles

## Source of Truth

Official uploaded PDFs are the only authoritative source.

Every extracted value must remain traceable to:

* PDF filename
* page number
* extracted table
* extraction timestamp

---

## Reproducibility

Running the same ingestion process on the same PDF must always produce the same output.

No manual intervention should be required.

---

## Explainability

Every metric shown in the dashboard or returned by the API must expose its source.

Users must always be able to navigate back to the original PDF page.

---

# Supported Documents

The system should support:

* Bilancio Consolidato
* Rendiconto Consolidato
* Bilancio di Previsione
* Nota Integrativa
* Relazione sulla Gestione

Initial development should focus on:

Bilancio Consolidato del Comune di Torino.

---

# Architecture

PDF
↓
pdfplumber
↓
Extraction Layer
↓
Normalization Layer
↓
Validation Layer
↓
DuckDB
↓
Query Layer (src/database/queries.py, read-only)
├── Streamlit Dashboard          (humans, interactive)
└── Static Publisher (src/publish) → site/  (HTML + JSON/CSV + llms.txt)
        └── consumed by the user's own LLM/agent

Both the dashboard and the static publisher consume the same database through the
read-only query layer. There is no HTTP API service. The LLM never reads PDFs
directly: it reads the published structured data, where every value is traceable
to its source document and page.

---

# Directory Structure

bilanciaTo/

├── data/
│
├── uploads/
│
├── extracted/
│
├── normalized/
│
├── database/
│
├── docs/
│
├── notebooks/
│
├── site/          (generated static, LLM-readable data site)
│
├── src/
│   ├── etl/
│   ├── extraction/
│   ├── normalization/
│   ├── database/   (schema, load, queries -- the read-only query layer)
│   ├── dashboard/  (Streamlit, reads DuckDB directly)
│   ├── publish/    (static site builder for LLM/agent access)
│   └── utils/
│
├── tests/
│
├── CLAUDE.md
├── README.md
├── pyproject.toml
└── Makefile

---

# Input Workflow

Users manually upload PDFs.

PDFs are stored in:

uploads/

Example:

uploads/
├── bilancio_consolidato_2024.pdf
├── bilancio_consolidato_2023.pdf
├── bilancio_consolidato_2022.pdf

No automatic download functionality should be implemented.

---

# Ingestion Workflow

The ingestion pipeline must:

1. detect document type
2. detect year
3. compute checksum
4. extract tables
5. normalize data
6. validate accounting consistency
7. load into DuckDB

CLI examples:

make ingest

or

python -m src.etl.ingest

---

# Document Registry

Each uploaded PDF becomes a record.

Table:

documents

Fields:

* id
* filename
* checksum
* document_type
* year
* upload_timestamp
* page_count

Checksums prevent duplicate imports.

---

# Extraction Layer

Location:

src/extraction/

Preferred library:

pdfplumber

Rationale:

On the Torino Bilancio Consolidato, tabula-py merges descriptions into the
numeric columns and splits cells across rows, losing the 2024/2023 separation.
pdfplumber keeps columns aligned and is pure-Python (no Java dependency), which
better serves financial correctness and reproducibility.

Fallbacks:

* tabula-py
* camelot

OCR must not be used unless extraction fails completely.

---

# Extraction Rules

Before extraction:

1. identify page ranges
2. detect tables
3. classify tables

Supported table types:

* balance_sheet
* income_statement
* cash_flow
* entity_list
* notes
* ownership
* debt
* assets
* liabilities
* other

Raw extracted tables must be saved.

Formats:

* CSV
* JSON
* Parquet

Location:

extracted/

---

# Normalization Layer

Location:

src/normalization/

Responsibilities:

* column cleanup
* decimal normalization
* header reconstruction
* merged cell reconstruction
* type conversion

Output:

normalized/

No financial values may be altered.

Only formatting transformations are allowed.

---

# Validation Layer

Validation errors must never be ignored.

Examples:

Assets = Liabilities + Equity

Balance sheet totals match published totals.

No duplicated metrics.

No malformed numeric values.

Validation reports must be stored.

---

# Database Layer

Preferred database:

DuckDB

Location:

database/bilanciato.duckdb

Reasoning:

* lightweight
* analytical workloads
* fast local execution
* excellent Parquet integration
* ideal for LLM retrieval workflows

---

# Canonical Schema

## documents

Fields:

* id
* filename
* year
* document_type
* checksum

---

## tables

Fields:

* id
* document_id
* page
* table_type
* raw_json

---

## metrics

Fields:

* id
* document_id
* year
* category
* metric_name
* value
* unit
* source_page

Examples:

* Total Assets
* Total Liabilities
* Net Equity
* Net Income
* Operating Revenue
* Operating Costs
* Financial Debt
* Cash

---

## entities

Fields:

* id
* document_id
* year
* name
* ownership_percentage
* consolidation_method
* entity_type

Examples:

* SMAT
* IREN
* GTT
* AFC Torino
* SORIS
* TRM

---

# Query Layer

Location:

src/database/queries.py

A read-only data-access layer over DuckDB (a `Repository` class). Opened
read-only; a fresh cursor per query makes it safe under Streamlit. Every method
that returns a financial value also returns its provenance (source_document +
source_page). Both the dashboard and the static publisher use this layer; there
is no HTTP API.

---

# Dashboard Layer

Location:

src/dashboard/

Framework:

Streamlit

Reads DuckDB directly through the query layer (no HTTP API). Usable by:

* citizens
* journalists
* researchers

Run: `streamlit run src/dashboard/app.py`.

---

# Dashboard Features

## Upload

Drag-and-drop PDF upload.

Pipeline status must be visible.

---

## Documents

List imported financial statements.

---

## Financial Statements

Interactive:

* balance sheet
* income statement
* debt analysis
* asset analysis

---

## Time Comparison

Compare years:

2022
2023
2024
...

---

## Entity Explorer

Explore consolidated entities.

Examples:

* SMAT
* IREN
* GTT
* AFC

---

## Source Explorer

Users can navigate from:

Metric
→ Table
→ PDF Page

---

# LLM Integration

The project does not run an LLM. Instead it publishes the structured data so that
any external assistant can ground answers on it.

Location:

src/publish/ → site/

Workflow:

User tells their assistant: "read the bilanciaTo data site and answer X"
↓
Assistant fetches site/llms.txt (and the linked HTML/JSON)
↓
Assistant reads structured figures (each with source document + page)
↓
Answer Generation, citing year / document / page

The assistant must never answer from PDF text or model memory: only from the
published structured data. Because the publication is static HTML + JSON + CSV +
llms.txt, an LLM that merely fetches the URL can consume it (unlike the live
Streamlit dashboard).

---

# Grounded Responses

Every figure in the published site carries:

* metric / voce
* year
* value + unit
* source document
* source page

The HTML pages render real numbers in the DOM next to their source page; the JSON
files carry the same fields. An assistant grounding on the site can therefore cite,
e.g.: TOTALE DELL'ATTIVO 2024 = 15.250.041.769,33 EUR (Bilancio Consolidato 2024,
pag. 15).

---

# Machine-Readable Data (for external LLMs)

The static site is the machine-readable surface:

* `site/llms.txt` — index for LLMs (the llms.txt convention): dataset summary,
  headline figures with provenance, links to pages and data files.
* `site/data/metrics.json` — flat records:
  `{year, category, code, metric_name, value, unit, source_page, source_document}`.
* `site/data/timeseries.json`, `entities.json`, `entity_metrics.json`, `note_items.json`,
  plus CSV equivalents.

Example record (data/metrics.json):

{
"year": 2024,
"category": "balance_sheet_assets",
"metric_name": "TOTALE DELL'ATTIVO",
"value": 15250041769.33,
"unit": "EUR",
"source_page": 15,
"source_document": "DEL-550-2025_Allegato_1_Bilancio_Consolidato_2024.pdf"
}

Build with `python -m src.publish.build`; host the `site/` folder anywhere static.

---

# Testing

Minimum coverage:

80%

Required test categories:

## Extraction

Verify tables are extracted correctly.

## Validation

Verify accounting identities.

## Database

Verify schema consistency and query-layer correctness.

## Publication

Verify the static site is generated with correct figures and intact provenance
(source_document + source_page) in both the HTML and the JSON/CSV exports.

---

# Coding Standards

Python 3.12+

Required libraries:

* pandas
* duckdb
* pdfplumber
* pyarrow
* streamlit
* plotly

Formatting:

* black
* ruff

Typing is mandatory.

Avoid unnecessary abstractions.

Prefer readability over cleverness.

---

# Initial Milestone

Phase 1:

* upload PDF
* extract tables
* build DuckDB
* publish the static data site
* basic dashboard

Success criteria:

A user uploads the Bilancio Consolidato 2024 PDF and can:

* inspect extracted tables
* browse key metrics
* compare years
* point an external assistant at the published data site and get answers grounded
  on the extracted data
* trace every answer back to the original PDF page

No answer should depend on model memory when the data exists in the database.
