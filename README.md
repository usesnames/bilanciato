# bilanciaTo

**Bilancio + Torino + Data.** An open-source pipeline that extracts the *Bilancio
Consolidato* (consolidated financial statements) of the Comune di Torino from the
official PDFs into a structured DuckDB database, then offers two ways to explore it:
an interactive dashboard for people, and a **static, LLM-readable data site** that
any AI assistant can be pointed at.

Every figure remains traceable to its **source document and PDF page**. No API
service and no API keys: an LLM grounds answers by reading the published data.

```
PDF → extraction (pdfplumber) → normalization → validation → DuckDB
                                                               │  (read-only query layer)
                                                               ├── Streamlit dashboard   (humans)
                                                               └── static publisher → site/
                                                                     HTML + JSON/CSV + llms.txt
                                                                     └── read by the user's own LLM
```

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## 1. Ingest the PDFs

Drop the official PDFs into `uploads/`, then:

```bash
python -m src.etl.ingest            # all profiled PDFs
python -m src.etl.ingest <file.pdf> # a single PDF
```

Ingestion detects the document type/year, computes a checksum (duplicates are
skipped), extracts and normalizes the tables, **validates accounting identities**
(Attivo = Passivo per year, aggregate, note movements), and loads into
`database/bilanciato.duckdb`. Layout per document is declared in
`src/utils/config.py` (`DocumentProfile`), keeping extraction reproducible.
Currently profiled: Bilancio Consolidato **2022, 2023, 2024** (data spans 2021–2024,
since each report also carries the prior year).

## 2. Dashboard (for humans)

```bash
make dashboard        # streamlit run src/dashboard/app.py  → http://localhost:8501
```

Reads DuckDB directly (no API). Sections: Panoramica, Prospetti di bilancio,
Confronto tra anni, Esplora le partecipate, Ricerca, Dati aperti / per LLM. Every
table shows the source PDF page.

## 3. Publish the LLM-readable data site

```bash
make publish          # python -m src.publish.build → site/
make serve-site       # build + serve site/ at http://localhost:8000 (preview)
```

This generates a **fully static** `site/`:

| File | For |
|---|---|
| `llms.txt` | LLM index (the [llms.txt](https://llmstxt.org) convention): summary, headline figures with provenance, links |
| `index.html`, `anno-<year>.html`, `partecipate.html` | human + LLM readable pages; **real numbers and source pages in the HTML** |
| `data/*.json`, `data/*.csv` | complete datasets: metrics, entities, entity_metrics, note_items, timeseries |

Because it is static, an LLM that *fetches the URL* can actually read it (a live
Streamlit app cannot be consumed that way). Host `site/` anywhere static (GitHub
Pages, Netlify, S3, or `python -m http.server`).

### Using it with an assistant

> "Read the bilanciaTo data site at `<url>/llms.txt` and tell me the consolidated
> total assets in 2024, citing the year and PDF page."

The assistant fetches `llms.txt`, follows it to the HTML/JSON, and answers from the
structured figures — e.g. *TOTALE DELL'ATTIVO 2024 = 15.250.041.769,33 EUR
(Bilancio Consolidato 2024, pag. 15)*. Every value carries `source_document` +
`source_page`, so the answer is verifiable.

## Tests

```bash
make test             # pytest
```

Tests run against the ingested database and self-skip if it has not been built yet.

## Design principles (see `CLAUDE.md`)

Transparency · traceability · reproducibility · machine readability · financial
correctness. The official PDFs are the only source of truth; no value is ever
manually edited, and an LLM never reads the PDFs directly — only the published
structured data.
