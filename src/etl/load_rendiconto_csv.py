"""Load a *rendiconto della gestione* from the Comune's "Formato aperto" CSVs.

Used when the official rendiconto PDF is unusable -- 2019's is only a poor scan --
so this year goes through the open-data CSVs instead of ``src.etl.ingest``. The
CSVs carry only the accrual/cash figures, so the loaded year has impegni/pagamenti
(spese) and accertamenti/riscossioni (entrate) -- no previsioni. Missione names are
borrowed from the already-loaded PDF years so codes/labels line up across years.

The step is idempotent: it removes any rendiconto_gestione document already loaded
for the year, validates (sum of voci == grand total), then loads.

Usage:
    python -m src.etl.load_rendiconto_csv                       # 2019 from uploads/
    python -m src.etl.load_rendiconto_csv 2019 <entrate.csv> <spese.csv>

Note: stop any running Streamlit/dashboard first -- its read-only connection holds
a DuckDB lock that blocks this writer.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.database import load
from src.database.schema import connect, init_schema
from src.etl import validate
from src.normalization.rendiconto_csv import normalize_entrate_csv, normalize_spese_csv
from src.utils.config import UPLOADS


def _missione_names(con) -> dict[str, str]:
    rows = con.execute(
        "SELECT DISTINCT code, name FROM rendiconto "
        "WHERE kind='spesa' AND level='voce' AND code IS NOT NULL"
    ).fetchall()
    return {code: name for code, name in rows}


def main(argv: list[str]) -> int:
    year = int(argv[0]) if argv else 2019
    entrate = Path(argv[1]) if len(argv) > 1 else UPLOADS / "rendiconto_entrate_2019.csv"
    spese = Path(argv[2]) if len(argv) > 2 else UPLOADS / "rendiconto_spese_2019.csv"
    print(f"==> rendiconto {year} (Formato aperto CSV)")
    print(f"    entrate={entrate.name}  spese={spese.name}")

    con = connect()
    init_schema(con)

    names = _missione_names(con)
    if not names:
        print("    ! no PDF rendiconto loaded yet -- missione names unavailable; load a PDF year first")
    items = normalize_entrate_csv(entrate) + normalize_spese_csv(spese, missione_names=names)

    checks = validate.validate_rendiconto_totals(items)
    for c in checks:
        print(f"    [{'OK ' if c.passed else 'FAIL'}] {c.name}: {c.detail}")
    if not all(c.passed for c in checks):
        print("    validation FAILED -- not loading into DuckDB")
        con.close()
        return 1

    # Idempotent: drop any rendiconto_gestione already loaded for this year.
    existing = [r[0] for r in con.execute(
        "SELECT id FROM documents WHERE document_type='rendiconto_gestione' AND year=?", [year]
    ).fetchall()]
    for did in existing:
        con.execute("DELETE FROM rendiconto WHERE document_id=?", [did])
        con.execute("DELETE FROM documents WHERE id=?", [did])
    if existing:
        print(f"    replaced existing rendiconto_gestione doc(s) for {year}: {existing}")

    h = hashlib.sha256()
    for p in (entrate, spese):
        h.update(Path(p).read_bytes())
    doc_id = load.insert_document(
        con,
        filename=f"rendiconto_{year}_formato_aperto_csv",
        checksum=h.hexdigest(),
        document_type="rendiconto_gestione",
        year=year,
        page_count=0,
        upload_timestamp=datetime.now(timezone.utc),
    )
    n = load.insert_rendiconto(con, doc_id, year, items)
    con.close()
    print(f"    loaded document id={doc_id}: {n} rendiconto rows for {year} "
          "(from CSV; impegni/pagamenti + accertamenti/riscossioni, no previsioni)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
