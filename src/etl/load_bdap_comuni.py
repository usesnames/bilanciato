"""Load the rendiconto summary of the 14 *città metropolitane* from the BDAP/RGS
per-region open-data ZIPs, for cross-city comparison (table ``rendiconto_comuni``).

Each comune sits in its region's ZIP, so a city is loadable only once that region's
ZIPs are present in ``uploads/bdap_rendiconto/``. Currently downloaded: Piemonte
(Torino) and Lombardia (Milano); add the others by downloading their region ZIPs
(same URL pattern, ``..._Schemi di bilancio_{REGION}.zip``) — this loader then picks
them up automatically. It reports which città metropolitane it found.

Full rebuild + idempotent: it TRUNCATES ``rendiconto_comuni`` and reloads everything
derivable from the ZIPs on disk, so the table always reflects exactly what is
downloaded. Reuses the BDAP normalizer (``src.normalization.bdap_rendiconto``) and
the canonical missione/titolo names already in the DB.

Usage:
    python -m src.etl.load_bdap_comuni                 # all metro cities found on disk

Note: stop any running Streamlit/dashboard first (DuckDB write lock).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from src.database.schema import connect, init_schema
from src.etl.load_bdap_rendiconto import (
    BDAP_DIR,
    _ENTRATE_MEMBER,
    _SPESE_MEMBER,
    _canonical_names,
    _find_member,
)
from src.normalization import bdap_rendiconto as bdap

# The 14 città metropolitane → the region whose BDAP ZIP holds them. The region
# string must match the ZIP filename token ``{year}_{REGION}.zip``. PIEMONTE and
# LOMBARDIA are confirmed against real files; the comune names (BDAP "Descrizione
# Comune", uppercase) and region tokens for the others are best-known values to be
# verified when each region's ZIPs are first downloaded (the loader logs misses).
CITTA_METROPOLITANE: dict[str, str] = {
    "TORINO": "PIEMONTE",
    "MILANO": "LOMBARDIA",
    "GENOVA": "LIGURIA",
    "VENEZIA": "VENETO",
    "BOLOGNA": "EMILIA-ROMAGNA",
    "FIRENZE": "TOSCANA",
    "ROMA": "LAZIO",
    "NAPOLI": "CAMPANIA",
    "BARI": "PUGLIA",
    "REGGIO DI CALABRIA": "CALABRIA",
    "PALERMO": "SICILIA",
    "MESSINA": "SICILIA",
    "CATANIA": "SICILIA",
    "CAGLIARI": "SARDEGNA",
}

_ZIP_RE = re.compile(r"^(\d{4})_(.+)\.zip$")


def _available_region_years() -> dict[str, list[int]]:
    """Scan the download dir → {REGION: [years]} for the ZIPs actually present."""
    out: dict[str, list[int]] = {}
    if not BDAP_DIR.exists():
        return out
    for p in BDAP_DIR.glob("*.zip"):
        m = _ZIP_RE.match(p.name)
        if m:
            out.setdefault(m.group(2).upper(), []).append(int(m.group(1)))
    for r in out:
        out[r].sort()
    return out


def _city_items(zip_path: Path, comune: str, spesa_names, entrata_names) -> list:
    with zipfile.ZipFile(zip_path) as zf:
        sp_hdr, sp_rows = bdap.load_riepilogo(zf.read(_find_member(zf, _SPESE_MEMBER)))
        en_hdr, en_rows = bdap.load_riepilogo(zf.read(_find_member(zf, _ENTRATE_MEMBER)))
    sp_sel = bdap.comune_rows(sp_hdr, sp_rows, comune)
    en_sel = bdap.comune_rows(en_hdr, en_rows, comune)
    if not sp_sel or not en_sel:
        return []
    return (bdap.normalize_spese(sp_hdr, sp_sel, names=spesa_names)
            + bdap.normalize_entrate(en_hdr, en_sel, names=entrata_names))


def main(argv: list[str]) -> int:
    avail = _available_region_years()
    print(f"==> regions on disk: {', '.join(sorted(avail)) or '(none)'}")
    con = connect()
    init_schema(con)
    spesa_names, entrata_names = _canonical_names(con)

    con.execute("DELETE FROM rendiconto_comuni")
    next_id = 1
    found_cities: dict[str, int] = {}
    for comune, region in CITTA_METROPOLITANE.items():
        years = avail.get(region.upper())
        if not years:
            continue
        loaded_years = []
        for year in years:
            zip_path = BDAP_DIR / f"{year}_{region.upper()}.zip"
            items = _city_items(zip_path, comune, spesa_names, entrata_names)
            if not items:
                continue
            source = f"BDAP Rendiconto SDB {year} (RGS/MEF) — {comune.title()}"
            records = [
                (next_id + i, comune, region.upper(), year, it.kind, it.level,
                 it.code or None, it.name, it.measure, it.value, "EUR", source)
                for i, it in enumerate(items)
            ]
            next_id += len(records)
            con.executemany(
                """INSERT INTO rendiconto_comuni
                   (id, comune, region, year, kind, level, code, name, measure, value, unit, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                records,
            )
            loaded_years.append(year)
        if loaded_years:
            found_cities[comune] = len(loaded_years)
            print(f"    {comune:18s} ({region}): {loaded_years[0]}–{loaded_years[-1]} "
                  f"({len(loaded_years)} years)")

    total = con.execute("SELECT count(*) FROM rendiconto_comuni").fetchone()[0]
    con.close()
    missing = [c for c, r in CITTA_METROPOLITANE.items() if r.upper() not in avail]
    print(f"==> done: {len(found_cities)} città metropolitane loaded, {total} rows")
    if missing:
        print(f"    not yet downloaded ({len(missing)}): {', '.join(missing)}")
    return 0 if found_cities else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
