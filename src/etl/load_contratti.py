"""Load the Comune di Torino public contracts from its L.190/2012 art.1 c.32
open datasets (one XML per reference year, ``uploads/contratti_l190/anac_<year>.xml``).

Each ``<lotto>`` becomes one ``contratti`` row: CIG, oggetto, struttura proponente,
procedura, aggiudicatario, importo di aggiudicazione, somme liquidate nell'anno,
numero partecipanti. The CIG is the join key to ANAC; ``capitolo_code`` (the bridge
to the budget) is left null here and filled later from the determinazioni.

Note on coverage: the L.190 obligation was repealed on 1 July 2023, so the series
effectively ends in 2023 (and the 2021-2022 files the Comune published are nearly
empty). 2024+ contracts live in ANAC/BDNCP or the bandi portal, to be added later
into this same table.

Usage:
    python -m src.etl.load_contratti                 # all XMLs under the dir
    python -m src.etl.load_contratti 2023            # only that year

Source XMLs (download into ``uploads/contratti_l190/anac_<year>.xml``):
    https://risorse.comune.torino.it/affidamenti/anac/<year>/dataset1.xml   (2019-2023)

Note: stop any running dashboard first (it holds a read lock).
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from src.utils.config import UPLOADS

CONTRATTI_DIR = UPLOADS / "contratti_l190"


def _loc(tag: str) -> str:
    return tag.split("}")[-1]


def _dec(text: str | None) -> Decimal | None:
    if not text:
        return None
    try:
        return Decimal(text.strip())
    except (InvalidOperation, AttributeError):
        return None


@dataclass
class Contratto:
    cig: str | None
    anno: int
    oggetto: str | None
    struttura: str | None
    scelta_contraente: str | None
    aggiudicatario: str | None
    aggiudicatario_cf: str | None
    n_partecipanti: int | None
    importo_aggiudicazione: Decimal | None
    importo_liquidato: Decimal | None
    data_inizio: str | None
    data_ultimazione: str | None


def _first_aggiudicatario(lotto: ET.Element) -> tuple[str | None, str | None]:
    """Return (ragioneSociale, codiceFiscale) of the first aggiudicatario."""
    for el in lotto.iter():
        if _loc(el.tag) == "aggiudicatario":
            rag = cf = None
            for s in el.iter():
                t = _loc(s.tag)
                if t == "ragioneSociale" and (s.text or "").strip():
                    rag = s.text.strip()
                elif t == "codiceFiscale" and (s.text or "").strip():
                    cf = s.text.strip()
            return rag, cf
    return None, None


def _count_partecipanti(lotto: ET.Element) -> int | None:
    for el in lotto.iter():
        if _loc(el.tag) == "partecipanti":
            n = sum(1 for c in el.iter() if _loc(c.tag) == "partecipante")
            return n or None
    return None


def parse_year(path, anno: int) -> list[Contratto]:
    root = ET.parse(path).getroot()
    out: list[Contratto] = []
    for lotto in (el for el in root.iter() if _loc(el.tag) == "lotto"):
        f: dict[str, str | None] = {}
        for ch in lotto:
            t = _loc(ch.tag)
            if t in ("cig", "oggetto", "sceltaContraente", "importoAggiudicazione",
                     "importoSommeLiquidate"):
                f[t] = (ch.text or "").strip() or None
            elif t == "strutturaProponente":
                f["struttura"] = next(
                    (s.text.strip() for s in ch.iter()
                     if _loc(s.tag) == "denominazione" and (s.text or "").strip()), None)
            elif t == "tempiCompletamento":
                for s in ch:
                    if _loc(s.tag) == "dataInizio":
                        f["dataInizio"] = (s.text or "").strip() or None
                    elif _loc(s.tag) == "dataUltimazione":
                        f["dataUltimazione"] = (s.text or "").strip() or None
        rag, cf = _first_aggiudicatario(lotto)
        di = f.get("dataInizio")
        du = f.get("dataUltimazione")
        out.append(Contratto(
            cig=f.get("cig"), anno=anno, oggetto=f.get("oggetto"),
            struttura=f.get("struttura"), scelta_contraente=f.get("sceltaContraente"),
            aggiudicatario=rag, aggiudicatario_cf=cf,
            n_partecipanti=_count_partecipanti(lotto),
            importo_aggiudicazione=_dec(f.get("importoAggiudicazione")),
            importo_liquidato=_dec(f.get("importoSommeLiquidate")),
            data_inizio=None if di in (None, "0000-00-00") else di,
            data_ultimazione=None if du in (None, "0000-00-00") else du,
        ))
    return out


def _xml_files(years: set[str]) -> list[tuple[int, object]]:
    files = sorted(CONTRATTI_DIR.glob("anac_*.xml"))
    picked = []
    for p in files:
        try:
            yr = int(p.stem.split("_")[-1])
        except ValueError:
            continue
        if not years or str(yr) in years:
            picked.append((yr, p))
    return picked


def main(argv: list[str]) -> int:
    from src.database.schema import connect, init_schema

    years = set(argv)
    files = _xml_files(years)
    if not files:
        print(f"nessun XML trovato in {CONTRATTI_DIR} per {sorted(years) or 'tutti gli anni'}")
        return 1

    con = connect()
    init_schema(con)
    total = 0
    next_id = con.execute("SELECT COALESCE(max(id), 0) FROM contratti").fetchone()[0]
    for anno, path in files:
        rows = parse_year(path, anno)
        con.execute("DELETE FROM contratti WHERE anno = ?", [anno])
        payload = [
            (next_id + 1 + i, c.cig, c.anno, c.oggetto, c.struttura, c.scelta_contraente,
             c.aggiudicatario, c.aggiudicatario_cf, c.n_partecipanti,
             c.importo_aggiudicazione, c.importo_liquidato, c.data_inizio,
             c.data_ultimazione, None, path.name)
            for i, c in enumerate(rows)
        ]
        next_id += len(payload)
        con.executemany(
            """INSERT INTO contratti
               (id, cig, anno, oggetto, struttura, scelta_contraente, aggiudicatario,
                aggiudicatario_cf, n_partecipanti, importo_aggiudicazione,
                importo_liquidato, data_inizio, data_ultimazione, capitolo_code,
                source_document)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )
        tot_agg = sum((c.importo_aggiudicazione or 0) for c in rows)
        print(f"    [OK ] {anno}: {len(rows)} contratti, "
              f"aggiudicato totale {tot_agg:,.0f} EUR")
        total += len(rows)
    con.close()
    print(f"    totale: {total} contratti caricati")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
