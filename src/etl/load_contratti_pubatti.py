"""Load the per-DD ``contratti`` table from the Comune di Torino *determinazioni
dirigenziali* harvested from pubatti.comune.torino.it.

This REPLACES the former L.190/2012 source. One ``contratti`` row per determinazione
that carries a CIG in its published oggetto (2023-2025); the impegni di spesa of each
act go into ``contratti_capitoli`` (one row per capitolo x anno di imputazione), whose
``capitolo_code`` joins ``rendiconto_capitoli`` -> the budget treemap.

Inputs (under ``uploads/determinazioni_pubatti/``, produced by the pubatti pipeline):
  - contratti_pubatti_base.csv         : one row per DD-with-CIG (anno, dd_numero,
        data_atto, idUd, idPubblicazione, cig, n_cig, importo_oggetto, oggetto)
  - determinazioni_capitoli_all.csv    : one row per (dd, capitolo) with anno_imp,
        importo, missione..., match

Usage:
    python -m src.etl.load_contratti_pubatti
Stop any running dashboard first (it holds a read lock).
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

from src.utils.config import UPLOADS

csv.field_size_limit(10 ** 7)
SRC = UPLOADS / "determinazioni_pubatti"
BASE = SRC / "contratti_pubatti_base.csv"
CAPS = SRC / "determinazioni_capitoli_all.csv"


def _dec_plain(s: str | None) -> Decimal | None:
    """Parse a plain float string like '2850.0' (importo from oggetto)."""
    if not s:
        return None
    try:
        return Decimal(s.strip())
    except (InvalidOperation, AttributeError):
        return None


def _dec_it(s: str | None) -> Decimal | None:
    """Parse an Italian-formatted amount like '92.619,60'."""
    if not s:
        return None
    try:
        return Decimal(s.strip().replace(".", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


def _int(s: str | None) -> int | None:
    try:
        return int(str(s).strip())
    except (ValueError, AttributeError):
        return None


def _iso_date(s: str | None) -> str | None:
    """'Dec 30, 2025, 12:00:00 AM' (pubatti) -> '2025-12-30'."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%b %d, %Y, %I:%M:%S %p").date().isoformat()
    except ValueError:
        return s


def main(argv: list[str]) -> int:
    from src.database.schema import connect, init_schema

    if not BASE.exists():
        print(f"manca {BASE} -- esegui prima la pipeline pubatti")
        return 1

    # capitoli per idUd
    caps_by_ud: dict[str, list[dict]] = {}
    if CAPS.exists():
        with open(CAPS, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter=";"):
                caps_by_ud.setdefault(r["idUd"], []).append(r)
    else:
        print(f"AVVISO: {CAPS} assente -- carico i contratti senza capitoli")

    con = connect()
    # full replace: drop child first (FK), then parent, then recreate fresh
    con.execute("DROP TABLE IF EXISTS contratti_capitoli")
    con.execute("DROP TABLE IF EXISTS contratti")
    init_schema(con)

    contratti_rows, capitoli_rows = [], []
    cid = 0
    capid = 0
    with open(BASE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            cid += 1
            ud = r["idUd"]
            caps = caps_by_ud.get(ud, [])
            distinct_caps = {c["capitolo"] for c in caps}
            contratti_rows.append((
                cid, _int(r["anno"]), r["dd_numero"], _iso_date(r["data_atto"]), ud,
                r["idPubblicazione"], r["cig"], _int(r["n_cig"]), r["oggetto"],
                _dec_plain(r.get("importo_oggetto")), len(distinct_caps), "pubatti",
            ))
            for c in caps:
                capid += 1
                capitoli_rows.append((
                    capid, cid, c["capitolo"], _int(c.get("anno_imp")),
                    _dec_it(c.get("importo")), c.get("match"),
                ))

    con.executemany(
        """INSERT INTO contratti
           (id, anno, dd_numero, data_atto, id_ud, id_pubblicazione, cig, n_cig,
            oggetto, importo, n_capitoli, source_document)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        contratti_rows,
    )
    con.executemany(
        """INSERT INTO contratti_capitoli
           (id, contratto_id, capitolo_code, anno_imp, importo, match_kind)
           VALUES (?,?,?,?,?,?)""",
        capitoli_rows,
    )

    n_with_cap = sum(1 for row in contratti_rows if row[10] > 0)
    by_year: dict[int, int] = {}
    for row in contratti_rows:
        by_year[row[1]] = by_year.get(row[1], 0) + 1
    con.close()

    print(f"caricati {len(contratti_rows)} contratti (per-DD), "
          f"{len(capitoli_rows)} righe capitoli")
    for y in sorted(by_year):
        print(f"    {y}: {by_year[y]} contratti")
    print(f"contratti con >=1 capitolo: {n_with_cap} "
          f"({100 * n_with_cap // max(len(contratti_rows), 1)}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
