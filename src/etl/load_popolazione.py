"""Load resident-population series into DuckDB, used to express the rendiconto
figures (and the cross-city comparison) in euro per abitante.

Standalone curated data (like ``debito``), one series per comune, keyed by
(comune, year). Sources:

* **Torino** — Comune di Torino, Servizio Stato Civile e Statistica, residenti
  iscritti in anagrafe al 31 dicembre (the figures the user provided), 2015-2025.
* **Milano, Roma, Venezia** — ISTAT, Bilancio demografico, popolazione residente
  al 31 dicembre, 2015-2024; the 2025 figures (Milano 1.399.079, Venezia 251.294,
  Roma 2.745.062) were supplied by the user, ISTAT not having published 31/12/2025
  yet. Note the slight methodological difference vs Torino's anagrafe count, and
  that from 2018 ISTAT figures reflect the censimento permanente.

Idempotent: replaces the whole table. Run while the dashboard is stopped (DuckDB
write lock).

Usage:
    python -m src.etl.load_popolazione
"""

from __future__ import annotations

from src.database.schema import connect, init_schema

SOURCE_TORINO = (
    "Comune di Torino — Servizio Stato Civile e Statistica, residenti iscritti in "
    "anagrafe al 31 dicembre (serie storica 2015-2024, Tavola 3.1; 2025 stessa fonte)"
)
SOURCE_ISTAT = (
    "ISTAT — Bilancio demografico, popolazione residente al 31 dicembre "
    "(dal 2018 censimento permanente)"
)

# Residenti al 31/12 di ciascun anno, per comune.
POPOLAZIONE: dict[str, dict[int, int]] = {
    "TORINO": {
        2015: 892_276, 2016: 888_921, 2017: 884_733, 2018: 879_004, 2019: 872_316,
        2020: 866_510, 2021: 861_636, 2022: 858_404, 2023: 860_973, 2024: 862_999,
        2025: 863_249,
    },
    "MILANO": {
        2015: 1_345_851, 2016: 1_351_562, 2017: 1_366_180, 2018: 1_395_980,
        2019: 1_406_242, 2020: 1_374_582, 2021: 1_349_930, 2022: 1_358_420,
        2023: 1_371_499, 2024: 1_365_698, 2025: 1_399_079,
    },
    "ROMA": {
        2015: 2_864_731, 2016: 2_873_494, 2017: 2_872_800, 2018: 2_820_219,
        2019: 2_808_293, 2020: 2_770_226, 2021: 2_749_031, 2022: 2_755_309,
        2023: 2_751_747, 2024: 2_747_290, 2025: 2_745_062,
    },
    "VENEZIA": {
        2015: 263_352, 2016: 261_905, 2017: 261_321, 2018: 259_961, 2019: 258_685,
        2020: 256_083, 2021: 251_944, 2022: 250_913, 2023: 250_290, 2024: 249_490,
        2025: 251_294,
    },
}

SOURCE: dict[str, str] = {
    "TORINO": SOURCE_TORINO,
    "MILANO": SOURCE_ISTAT,
    "ROMA": SOURCE_ISTAT,
    "VENEZIA": SOURCE_ISTAT,
}


def main() -> int:
    con = connect()
    init_schema(con)
    con.execute("DELETE FROM popolazione")
    rows = [
        (comune, y, r, SOURCE[comune])
        for comune, series in POPOLAZIONE.items()
        for y, r in sorted(series.items())
    ]
    con.executemany(
        "INSERT INTO popolazione (comune, year, residenti, source) VALUES (?, ?, ?, ?)",
        rows,
    )
    con.close()
    for comune, series in POPOLAZIONE.items():
        print(f"loaded {len(series)} years for {comune} "
              f"({min(series)}-{max(series)})")
    print(f"total: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
