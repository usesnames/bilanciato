.PHONY: install ingest load-bdap-rendiconto load-bdap-comuni load-debito load-popolazione load-entity-statements load-rendiconto-csv dashboard publish serve-site test lint format clean

PY := .venv/bin/python
PIP := .venv/bin/pip

install:  ## install all dependencies into .venv
	$(PIP) install -e ".[dev]"

ingest:  ## run the ETL over every profiled PDF in uploads/
	$(PY) -m src.etl.ingest

load-bdap-rendiconto:  ## (re)load Torino's rendiconto summary 2016-2025 from the BDAP/RGS open-data ZIPs
	$(PY) -m src.etl.load_bdap_rendiconto

load-bdap-comuni:  ## (re)load the città-metropolitane comparison from the BDAP/RGS ZIPs on disk
	$(PY) -m src.etl.load_bdap_comuni

load-debito:  ## load the curated municipal-debt series (Collegio dei revisori) into DuckDB
	$(PY) -m src.etl.load_debito

load-popolazione:  ## load the Comune di Torino resident-population series (for euro per-capita)
	$(PY) -m src.etl.load_popolazione

load-entity-statements:  ## load the partecipate civil-code statements (SP+CE) from uploads/partecipate
	$(PY) -m src.etl.load_entity_statements

load-rendiconto-csv:  ## load a rendiconto from the Formato aperto CSVs (2019, PDF unusable)
	$(PY) -m src.etl.load_rendiconto_csv

dashboard:  ## start the Streamlit dashboard on :8501 (reads DuckDB directly)
	PYTHONPATH=. .venv/bin/streamlit run src/dashboard/app.py

publish:  ## build the static, LLM-readable data site into site/
	$(PY) -m src.publish.build

serve-site: publish  ## build then serve site/ locally on :8000 for preview
	$(PY) -m http.server 8000 --directory site

test:  ## run the test suite
	$(PY) -m pytest

lint:  ## ruff check
	.venv/bin/ruff check src tests

format:  ## black + ruff --fix
	.venv/bin/black src tests
	.venv/bin/ruff check --fix src tests

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
