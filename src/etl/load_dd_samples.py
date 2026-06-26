"""Load the DD-sourced 2025 sample contracts into the ``contratti`` table.

These *determinazioni dirigenziali* were downloaded from bandi.comune.torino.it
and run through :mod:`src.etl.parse_dd`. The L.190 series ends in 2023, so 2024+
contracts have to come from the DDs themselves; this module is the worked
example of that path — each row carries the ``capitolo_code`` bridge to
``rendiconto_capitoli`` where the DD's value row was legible enough to verify the
code against the rendiconto.

The data below is hand-verified from the parser output (the parser finds the
capitolo *name* reliably; the numeric code is confirmed here against the
rendiconto, fixing wrap-truncated codes by name match):

  - sample_1 GTT titoli viaggio : parsed code 08610000101 was truncated →
    086100001014 ("SERVIZI SOCIALI - SPESE GENERALI - SPESE VARIE - settore 019").
  - sample_3 formazione SENIOR  : 3 capitoli; the principal (largest spesa) is
    082400023005 (the other two are noted in the oggetto, since ``contratti``
    holds one capitolo per row).
  - sample_4 manut. Circ. 6     : capitoli 2400008002 / 5600001000 are
    *circoscrizionali*, absent from rendiconto_capitoli → no bridge (null).
  - sample_5 albo B1 disabili   : 087500009001 (two CIG; the principal recorded).
  - sample_2 is an image-only scan → no extractable data, omitted.

Usage:
    python -m src.etl.load_dd_samples        # stop the dashboard first (write lock)
"""

from __future__ import annotations

from decimal import Decimal

# cig, anno, oggetto, aggiudicatario, scelta_contraente, importo_aggiudicazione,
# capitolo_code (bridge, or None), source_document
SAMPLES = [
    (None, 2025,
     "Fornitura di abbonamenti impersonali, tagliandi di sosta urbani e biglietti "
     "city per il personale dipendente - affidamento a GTT S.p.A.",
     "GTT S.p.A.", "Affidamento diretto art. 50 c.1 lett. b (senza CIG)",
     Decimal("6895.00"), "086100001014", "DD_3843_2025_gtt.pdf"),
    ("B79A13D4B1", 2025,
     "Servizio di formazione “Senior Squadra Lettura” - Progetto SxT (Senior x "
     "Torino, atto II), cofinanziato Regione Piemonte. Capitoli secondari: "
     "087300039003 (spesa €1.490,00), 009900060002 (entrata €1.490,00)",
     None, "Affidamento diretto art. 50 c.1 lett. b",
     Decimal("17766.09"), "082400023005", "DD-4652-2025.pdf"),
    ("B180F634A5", 2024,
     "Circ. 6 - servizi di piccola manutenzione ordinaria su fabbricati e impianti "
     "sportivi della Circoscrizione 6, anno 2024 (capitoli circoscrizionali "
     "2400008002 / 5600001000, non presenti nel rendiconto)",
     None, "Affidamento diretto art. 50 c.1 lett. b",
     Decimal("30000.00"), None, "DD-2906-2024.pdf"),
    ("B7024DCE7E", 2025,
     "C.4 Albo prestatori servizi socio-sanitari sottosezione B1: percorsi socio "
     "educativi estivi per persone con disabilità, anno 2025 (secondo CIG del "
     "lotto: B702475980)",
     None, "Affidamento diretto art. 50 c.1 lett. b",
     Decimal("52586.50"), "087500009001", "DD-3560-2025.pdf"),
]


def main() -> int:
    from src.database.schema import connect, init_schema

    con = connect()
    init_schema(con)

    sources = tuple(s[7] for s in SAMPLES)
    con.execute(
        f"DELETE FROM contratti WHERE source_document IN ({','.join(['?'] * len(sources))})",
        list(sources),
    )
    next_id = con.execute("SELECT COALESCE(max(id), 0) FROM contratti").fetchone()[0]
    payload = [
        (next_id + 1 + i, cig, anno, oggetto, None, scelta, agg, None, None,
         importo, None, None, None, cap, src)
        for i, (cig, anno, oggetto, agg, scelta, importo, cap, src) in enumerate(SAMPLES)
    ]
    con.executemany(
        """INSERT INTO contratti
           (id, cig, anno, oggetto, struttura, scelta_contraente, aggiudicatario,
            aggiudicatario_cf, n_partecipanti, importo_aggiudicazione,
            importo_liquidato, data_inizio, data_ultimazione, capitolo_code,
            source_document)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        payload,
    )
    bridged = sum(1 for s in SAMPLES if s[6])
    print(f"    [OK ] {len(SAMPLES)} contratti DD caricati "
          f"({bridged} con capitolo collegato, {len(SAMPLES) - bridged} senza)")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
