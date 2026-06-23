"""Load the *rendiconto della gestione* (summary, per-missione/per-titolo) of a
comune from the BDAP / RGS open-data ZIPs, replacing any PDF-sourced rendiconto.

This is now the authoritative source for the Comune di Torino's rendiconto
summary: the official RGS open data (https://openbdap.rgs.mef.gov.it) gives a
uniform, machine-readable series 2016–2025, where the previous PDF parsing only
reached 2019–2025 (and 2019 lacked the previsioni). The figures were verified to
match the PDF-parsed values to the cent (impegni / pagamenti / accertamenti /
riscossioni) for an overlapping year.

It does NOT touch ``rendiconto_capitoli`` (the analytic per-capitolo detail, a
separate ``rendiconto_capitoli`` document type): the BDAP riepilogo files are only
at the missione/titolo level, exactly like this summary, and the capitoli continue
to come from the analytic per-capitoli PDFs and still reconcile to these totals.

Each year's ZIP lives in ``uploads/bdap_rendiconto/{year}_{REGION}.zip`` and holds
one ``Spese Riepilogo Missioni`` and one ``Entrate Riepilogo Titoli`` CSV for all
comuni of the region. We read those two members in-memory (a few MB each), select
the target comune, validate (sum of voci == grand total) and load.

The step is idempotent: it removes any ``rendiconto_gestione`` document already
loaded for each processed year, then loads the BDAP one.

Usage:
    python -m src.etl.load_bdap_rendiconto                 # Torino, 2016–2025
    python -m src.etl.load_bdap_rendiconto 2016 2017       # only those years
    python -m src.etl.load_bdap_rendiconto --comune TORINO --region PIEMONTE

Note: stop any running Streamlit/dashboard first — its read-only connection holds
a DuckDB lock that blocks this writer.
"""

from __future__ import annotations

import argparse
import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from src.database import load
from src.database.schema import connect, init_schema
from src.etl import validate
from src.normalization import bdap_rendiconto as bdap
from src.utils.config import UPLOADS

BDAP_DIR = UPLOADS / "bdap_rendiconto"
DEFAULT_YEARS = tuple(range(2016, 2026))
DEFAULT_COMUNE = "TORINO"
DEFAULT_REGION = "PIEMONTE"

# Substrings identifying the two riepilogo members inside a region ZIP. The
# "- Voce di Riepilogo" companion files (printed grand-total only) are excluded.
_SPESE_MEMBER = "Spese Riepilogo Missioni"
_ENTRATE_MEMBER = "Entrate Riepilogo Titoli"
_EXCLUDE = "Voce di Riepilogo"


def _find_member(zf: zipfile.ZipFile, needle: str) -> str:
    cands = [n for n in zf.namelist()
             if needle in n and _EXCLUDE not in n and n.lower().endswith(".csv")]
    if not cands:
        raise FileNotFoundError(f"no '{needle}' CSV in {zf.filename}")
    # Shortest name = the plain riepilogo (avoids any longer variant).
    return min(cands, key=len)


def _canonical_names(con) -> tuple[dict[str, str], dict[str, str]]:
    """Snapshot the missione/titolo display names already in the DB, so codes keep
    consistent (properly-cased) labels across all years. Falls back to the BDAP
    descrizione for any code not yet seen."""
    spesa = {c: n for c, n in con.execute(
        "SELECT DISTINCT code, name FROM rendiconto "
        "WHERE kind='spesa' AND level='voce' AND code IS NOT NULL").fetchall()}
    entrata = {c: n for c, n in con.execute(
        "SELECT DISTINCT code, name FROM rendiconto "
        "WHERE kind='entrata' AND level='voce' AND code IS NOT NULL").fetchall()}
    return spesa, entrata


def _load_year(con, year: int, region: str, comune: str,
               spesa_names: dict[str, str], entrata_names: dict[str, str]) -> bool:
    zip_path = BDAP_DIR / f"{year}_{region}.zip"
    if not zip_path.exists():
        print(f"==> {year}: {zip_path.name} not found — skipping")
        return False
    print(f"==> {year}: {zip_path.name}")

    with zipfile.ZipFile(zip_path) as zf:
        spese_name = _find_member(zf, _SPESE_MEMBER)
        entrate_name = _find_member(zf, _ENTRATE_MEMBER)
        sp_hdr, sp_rows = bdap.load_riepilogo(zf.read(spese_name))
        en_hdr, en_rows = bdap.load_riepilogo(zf.read(entrate_name))

    sp_sel = bdap.comune_rows(sp_hdr, sp_rows, comune)
    en_sel = bdap.comune_rows(en_hdr, en_rows, comune)
    if not sp_sel or not en_sel:
        print(f"    ! comune '{comune}' not found (spese={len(sp_sel)}, entrate={len(en_sel)}) — skipping")
        return False

    items = (bdap.normalize_spese(sp_hdr, sp_sel, names=spesa_names)
             + bdap.normalize_entrate(en_hdr, en_sel, names=entrata_names))

    checks = validate.validate_rendiconto_totals(items)
    for c in checks:
        print(f"    [{'OK ' if c.passed else 'FAIL'}] {c.name}: {c.detail}")
    if not all(c.passed for c in checks):
        print(f"    validation FAILED for {year} — not loading")
        return False

    # Idempotent: drop any rendiconto_gestione already loaded for this year.
    existing = [r[0] for r in con.execute(
        "SELECT id FROM documents WHERE document_type='rendiconto_gestione' AND year=?",
        [year]).fetchall()]
    for did in existing:
        con.execute("DELETE FROM rendiconto WHERE document_id=?", [did])
        con.execute("DELETE FROM documents WHERE id=?", [did])
    if existing:
        print(f"    replaced existing rendiconto_gestione doc(s) for {year}: {existing}")

    h = hashlib.sha256()
    h.update(zip_path.name.encode())
    h.update(b"|")
    h.update(comune.encode())
    h.update(str(year).encode())
    doc_id = load.insert_document(
        con,
        filename=f"BDAP Rendiconto SDB {year} (RGS/MEF) — Comune di {comune.title()}",
        checksum=h.hexdigest(),
        document_type="rendiconto_gestione",
        year=year,
        page_count=0,
        upload_timestamp=datetime.now(timezone.utc),
    )
    n = load.insert_rendiconto(con, doc_id, year, items)
    n_voci = sum(1 for it in items if it.level == "voce")
    print(f"    loaded document id={doc_id}: {n} rows ({n_voci} voci; "
          "previsioni + impegni/accertamenti + pagamenti/riscossioni)")
    return True


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Load a comune's rendiconto from BDAP/RGS ZIPs.")
    ap.add_argument("years", nargs="*", type=int, help="years to load (default 2016–2025)")
    ap.add_argument("--comune", default=DEFAULT_COMUNE, help="Descrizione Comune (default TORINO)")
    ap.add_argument("--region", default=DEFAULT_REGION, help="region of the ZIPs (default PIEMONTE)")
    args = ap.parse_args(argv)
    years = tuple(args.years) if args.years else DEFAULT_YEARS
    comune = args.comune.upper()

    print(f"==> BDAP rendiconto: comune={comune} region={args.region} years={years[0]}–{years[-1]}")
    con = connect()
    init_schema(con)
    spesa_names, entrata_names = _canonical_names(con)

    loaded = 0
    for year in years:
        if _load_year(con, year, args.region.upper(), comune, spesa_names, entrata_names):
            loaded += 1
    con.close()
    print(f"==> done: {loaded}/{len(years)} years loaded")
    return 0 if loaded else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
