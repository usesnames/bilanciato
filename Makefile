.PHONY: install ingest dashboard publish serve-site test lint format clean

PY := .venv/bin/python
PIP := .venv/bin/pip

install:  ## install all dependencies into .venv
	$(PIP) install -e ".[dev]"

ingest:  ## run the ETL over every profiled PDF in uploads/
	$(PY) -m src.etl.ingest

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
