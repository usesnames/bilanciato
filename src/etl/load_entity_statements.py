"""Load the financial statements (SP + CE) of the most important partecipate from
their deposited *fascicolo di bilancio* PDFs in ``uploads/partecipate/``.

Each partecipata is described by an ``EntityFascicolo``: which PDF, which pages
carry the Attivo / Passivo / Conto economico, and the two years the fascicolo
reports. The slug reuses the consolidato canonical slug so the statements attach
to the same entity in the explorer (see ``entity_names.py``).

All years found in a fascicolo are stored (the dashboard may show only the latest
two); the loader is idempotent per entity (delete that entity's rows, re-insert).
Before loading, it validates the parse: TOTALE ATTIVO == TOTALE PASSIVO E NETTO,
and the CE result equals patrimonio netto's utile d'esercizio.

Usage:
    python -m src.etl.load_entity_statements                 # all configured
    python -m src.etl.load_entity_statements infratrasporti_to

Note: stop any running dashboard first — its read-only connection holds a lock.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from decimal import Decimal

import pdfplumber

from src.etl.curated_amiat import curated_items as _amiat_curated
from src.etl.curated_iren import curated_items as _iren_curated
from src.etl.curated_smat import curated_items as _smat_curated
from src.normalization import entity_statements as es
from src.utils.config import UPLOADS

PARTECIPATE_DIR = UPLOADS / "partecipate"

# Entities whose figures are hand-curated (transcribed + verified) rather than
# parsed: their PDFs are too irregular for the generic coordinate parser.
CURATED = {"iren": _iren_curated, "smat": _smat_curated, "amiat": _amiat_curated}


@dataclass
class EntityFascicolo:
    slug: str                 # canonical slug (reused from the consolidato)
    name: str                 # display name
    filename: str             # PDF under uploads/partecipate/
    year: int                 # current year of the fascicolo
    prev_year: int            # prior-year column
    attivo_pages: tuple[int, ...]
    passivo_pages: tuple[int, ...]
    conto_economico_pages: tuple[int, ...]
    ifrs: bool = False                      # True → IAS/IFRS layout
    migliaia: int = 1                       # scale factor (1000 when PDF reports in thousands)
    consolidated: bool = False              # True → IFRS consolidated (group) statements
    rapporti_pages: tuple[int, ...] = ()    # related-party supplement pages (IFRS only)
    rapporti_entity: str = "Comune di Torino"  # counterparty name as it appears in the PDF


# Configured partecipate. Pages are 1-based, as printed in the fascicolo.
FASCICOLI: list[EntityFascicolo] = [
    EntityFascicolo(
        slug="infratrasporti_to",
        name="Infratrasporti.TO S.r.l.",
        filename="INFRA.TO_Fascicolo-di-Bilancio-2024.pdf",
        year=2024, prev_year=2023,
        attivo_pages=(80, 81),
        passivo_pages=(82,),
        conto_economico_pages=(83, 84),
    ),
    EntityFascicolo(
        slug="iren",
        name="Iren S.p.A.",
        filename="Relazione Annuale Integrata 2024.pdf",
        year=2024, prev_year=2023,
        attivo_pages=(306,),
        passivo_pages=(307,),
        conto_economico_pages=(308,),
        ifrs=True,
        migliaia=1000,
        consolidated=True,
        rapporti_pages=(412, 413),
        rapporti_entity="Comune Torino",
    ),
    EntityFascicolo(
        slug="smat",
        name="SMAT S.p.A. e suo Gruppo",
        filename="BILANCIO-SMAT-31-12-2024-light.pdf",
        year=2024, prev_year=2023,
        attivo_pages=(149,),
        passivo_pages=(150,),
        conto_economico_pages=(151,),
        ifrs=True,
        migliaia=1,
        consolidated=True,
        rapporti_pages=(192,),
        rapporti_entity="Città di Torino",
    ),
    EntityFascicolo(
        slug="amiat",
        name="AMIAT S.p.A.",
        filename="Bilancio Amiat 2024.pdf",
        year=2024, prev_year=2023,
        attivo_pages=(41,),
        passivo_pages=(41,),
        conto_economico_pages=(42,),
        ifrs=True,
        migliaia=1,
        consolidated=False,
        rapporti_pages=(95,),
        rapporti_entity="Comune Torino",
    ),
]


def _words(pdf, pages: tuple[int, ...]) -> dict[int, list[dict]]:
    return {p: pdf.pages[p - 1].extract_words() for p in pages}


def _parse(fasc: EntityFascicolo) -> list[es.StatementItem]:
    if fasc.slug in CURATED:
        return CURATED[fasc.slug](fasc)
    path = PARTECIPATE_DIR / fasc.filename
    items: list[es.StatementItem] = []
    with pdfplumber.open(path) as pdf:
        if fasc.ifrs:
            for category, pages in (
                (es.ATTIVO, fasc.attivo_pages),
                (es.PASSIVO, fasc.passivo_pages),
                (es.CONTO_ECONOMICO, fasc.conto_economico_pages),
            ):
                items += es.normalize_statement_ifrs(
                    _words(pdf, pages), category,
                    year=fasc.year, prev_year=fasc.prev_year,
                    migliaia=fasc.migliaia)
            if fasc.rapporti_pages:
                # first half → page-488 column definitions; second half → page-489
                rp = fasc.rapporti_pages
                mid = len(rp) // 2
                p_left  = {p: pdf.pages[p - 1].extract_words() for p in rp[:mid]}
                p_right = {p: pdf.pages[p - 1].extract_words() for p in rp[mid:]}
                rp_kwargs: dict = dict(
                    year=fasc.year,
                    entity=fasc.rapporti_entity,
                    migliaia=fasc.migliaia,
                )
                if fasc.consolidated:
                    rp_kwargs["label_x0_max"] = es.RP_CONSOL_LABEL_X0_MAX
                    rp_kwargs["col_bounds"]   = es.RP_CONSOL_COL_BOUNDS
                items += es.normalize_rapporti_ifrs(p_left, p_right, **rp_kwargs)
        else:
            for category, pages in (
                (es.ATTIVO, fasc.attivo_pages),
                (es.PASSIVO, fasc.passivo_pages),
                (es.CONTO_ECONOMICO, fasc.conto_economico_pages),
            ):
                items += es.normalize_statement(
                    _words(pdf, pages), category,
                    year=fasc.year, prev_year=fasc.prev_year)
    return items


def _validate(fasc: EntityFascicolo, items: list[es.StatementItem]) -> list[str]:
    """Return a list of problems; empty means the parse reconciles."""
    def find(category: str, year: int, pred) -> Decimal | None:
        return next((i.value for i in items
                     if i.category == category and i.year == year
                     and i.related_party is None
                     and pred(i.name.replace(" ", "").upper())), None)

    problems: list[str] = []
    for yr in (fasc.year, fasc.prev_year):
        if fasc.ifrs:
            # Grand total only: "TOTALE ATTIVIT(A'|À)", never the "non correnti"
            # / "correnti" subtotals. "PASSIVIT" (no trailing A) is accent-safe.
            ta = find(es.ATTIVO,  yr,
                      lambda n: n.startswith("TOTALEATTIV") and "CORRENTI" not in n)
            tp = find(es.PASSIVO, yr,
                      lambda n: "PATRIMONIO" in n and "PASSIVIT" in n)
            if ta is None or tp is None:
                problems.append(f"{yr}: totale attivo/passivo non trovato ({ta} / {tp})")
            elif ta != tp:
                problems.append(f"{yr}: attivo {ta} != passivo {tp}")
            if fasc.consolidated:
                # Consolidated CE shows total result + attribution split; SP shows parent share.
                # Match the "attribuibile agli azionisti" CE line against SP patrimonio netto.
                ce = find(es.CONTO_ECONOMICO, yr,
                          lambda n: "ATTRIBUIBILEAGLI" in n and "AZIONISTI" in n)
                sp = find(es.PASSIVO, yr,
                          lambda n: "RISULTATONETTO" in n and "PERIODO" in n)
            else:
                ce = find(es.CONTO_ECONOMICO, yr,
                          lambda n: "RISULTATONETTO" in n and "PERIODO" in n
                                    and "ATTIVITA" not in n)
                sp = find(es.PASSIVO, yr,
                          lambda n: "RISULTATONETTO" in n and "PERIODO" in n)
            if ce is not None and sp is not None and ce != sp:
                problems.append(f"{yr}: risultato netto CE {ce} != SP {sp}")
        else:
            ta = find(es.ATTIVO, yr, lambda n: n == "TOTALEATTIVO")
            tp = find(es.PASSIVO, yr, lambda n: n.startswith("TOTALEPASSIVOENET"))
            if ta is None or tp is None:
                problems.append(f"{yr}: totale attivo/passivo non trovato ({ta} / {tp})")
            elif ta != tp:
                problems.append(f"{yr}: attivo {ta} != passivo {tp}")
            ce = find(es.CONTO_ECONOMICO, yr,
                      lambda n: n.startswith("21)UTILE") or "UTILE(PERDITA)DELL'ESER" in n)
            sp = find(es.PASSIVO, yr, lambda n: "UTILE(PERDITA)D'ESERCIZIO" in n)
            if ce is not None and sp is not None and ce != sp:
                problems.append(f"{yr}: utile CE {ce} != utile SP {sp}")
    return problems


def _load_one(con, fasc: EntityFascicolo) -> int:
    items = _parse(fasc)
    problems = _validate(fasc, items)
    for p in problems:
        print(f"    [FAIL] {p}")
    if problems:
        raise SystemExit(f"validazione fallita per {fasc.slug}; non carico")
    con.execute("DELETE FROM entity_statements WHERE entity_slug = ?", [fasc.slug])
    start = con.execute("SELECT COALESCE(max(id), 0) FROM entity_statements").fetchone()[0]
    rows = [
        (start + 1 + n, fasc.slug, fasc.name, it.year, it.category, it.seq,
         it.code or None, it.name, it.value, "EUR", it.is_total,
         it.related_party, fasc.filename, it.source_page)
        for n, it in enumerate(items)
    ]
    con.executemany(
        """INSERT INTO entity_statements
           (id, entity_slug, entity_name, year, category, seq, code, name,
            value, unit, is_total, related_party, source_document, source_page)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    print(f"    [OK ] {fasc.slug}: {len(rows)} righe "
          f"({fasc.prev_year}+{fasc.year}), quadratura verificata")
    return len(rows)


def main(argv: list[str]) -> int:
    from src.database.schema import connect, init_schema

    wanted = set(argv)
    fascicoli = [f for f in FASCICOLI if not wanted or f.slug in wanted]
    if not fascicoli:
        print(f"nessuna partecipata corrisponde a {sorted(wanted)}; "
              f"disponibili: {[f.slug for f in FASCICOLI]}")
        return 1
    con = connect()
    init_schema(con)
    total = sum(_load_one(con, f) for f in fascicoli)
    con.close()
    print(f"    totale: {total} righe per {len(fascicoli)} partecipata/e")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
