"""Load the curated municipal-debt series into DuckDB.

The debt figures (``src/normalization/debito.py``) are transcribed from the
Relazioni del Collegio dei revisori dei conti, not extracted from a PDF, so they
have their own loader rather than going through ``src.etl.ingest``. This step is
idempotent: it validates the series, then replaces the ``debito`` table wholesale.

Usage:
    python -m src.etl.load_debito

Note: stop any running Streamlit/dashboard first -- its read-only connection holds
a DuckDB lock that blocks this writer.
"""

from __future__ import annotations

import sys

from src.database import load
from src.database.schema import connect, init_schema
from src.etl import validate
from src.normalization.debito import debito_items


def main() -> int:
    items = debito_items()
    checks = validate.validate_debito(items)
    for c in checks:
        print(f"    [{'OK ' if c.passed else 'FAIL'}] {c.name}: {c.detail}")
    if not all(c.passed for c in checks):
        print("    validation FAILED -- not loading the debt series into DuckDB")
        return 1

    con = connect()
    init_schema(con)
    n = load.replace_debito(con, items)
    con.close()
    years = sorted({it.year for it in items})
    print(f"    loaded {n} debito rows for {years[0]}-{years[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
