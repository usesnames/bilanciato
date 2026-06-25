"""Hand-curated CIT statements, transcribed from the *Rendiconto della gestione
2024* of the Consorzio Intercomunale Torino (three PDFs: SP attivo, SP passivo,
conto economico).

CIT is a public-law consortium, so its prospetti follow the harmonized public
accounting scheme (D.Lgs 118/2011, Allegato 10) rather than the plain civil
code — different labels ("TOTALE DELL'ATTIVO", "RISULTATO DELL'ESERCIZIO"),
components grouped as «componenti positivi/negativi della gestione». Values are
in euros with cents.

Convention (as for the other civil-code entities): section-B cost components
are positive and "TOTALE COMPONENTI NEGATIVI DELLA GESTIONE (B)" is negative,
so the result chain reads A + B + C + E − imposte. Oneri straordinari and
imposte are likewise entered negative.

Source: uploads/partecipate/CIT_bilancio_2024/ (Allegato 10, esercizio 2024).
No related-party detail is published in these prospetti.
"""

from __future__ import annotations

from decimal import Decimal

from src.normalization import entity_statements as es

SOURCE_DOCUMENT = "CIT_bilancio_2024 (Rendiconto della gestione, Allegato 10)"

YEAR_CUR = 2024
YEAR_PREV = 2023

# (code, name, is_total, value_2024, value_2023) — euros with cents, as strings.
_ATTIVO: list[tuple[str, str, bool, str, str]] = [
    ("2)", "B.I.2) Costi di ricerca, sviluppo e pubblicità", False, "21977.63", "184861.81"),
    ("3)", "B.I.3) Diritti di brevetto e utilizzazione opere dell'ingegno", False, "131.99", "1176.22"),
    ("6)", "B.I.6) Immobilizzazioni immateriali in corso ed acconti", False, "1280.20", "26.47"),
    ("9)", "B.I.9) Altre immobilizzazioni immateriali", False, "0", "10670.47"),
    ("", "Totale immobilizzazioni immateriali", True, "23389.82", "196734.97"),
    ("2.1", "B.II.2.1) Terreni", False, "35820195.55", "35820195.55"),
    ("2.2", "B.II.2.2) Fabbricati", False, "206662829.15", "188336261.23"),
    ("2.6", "B.II.2.6) Macchine per ufficio e hardware", False, "9510.64", "3189.22"),
    ("2.7", "B.II.2.7) Mobili e arredi", False, "5667.97", "11489.83"),
    ("2.99", "B.II.2.99) Altri beni materiali", False, "0", "7966.20"),
    ("3", "B.II.3) Immobilizzazioni materiali in corso ed acconti", False, "2821107.33", "24481476.45"),
    ("", "Totale immobilizzazioni materiali", True, "245319310.64", "248660578.48"),
    ("", "TOTALE IMMOBILIZZAZIONI (B)", True, "245342700.46", "248857313.45"),
    ("2", "C.II.2) Crediti per trasferimenti e contributi", False, "1228549.86", "1252299.69"),
    ("3", "C.II.3) Crediti verso clienti ed utenti", False, "659685.65", "689051.01"),
    ("4", "C.II.4) Altri crediti", False, "1152734.02", "23240480.45"),
    ("", "Totale crediti", True, "3040969.53", "25181831.15"),
    ("1", "C.IV.1) Conto di tesoreria", False, "12238256.94", "12289970.79"),
    ("2", "C.IV.2) Altri depositi bancari e postali", False, "44360.63", "50308.39"),
    ("", "Totale disponibilità liquide", True, "12282617.57", "12340279.18"),
    ("", "TOTALE ATTIVO CIRCOLANTE (C)", True, "15323587.10", "37522110.33"),
    ("", "TOTALE DELL'ATTIVO (A+B+C+D)", True, "260666287.56", "286379423.78"),
]

_PASSIVO: list[tuple[str, str, bool, str, str]] = [
    ("I", "A.I) Fondo di dotazione", False, "103320181.86", "103320181.86"),
    ("II", "A.II) Riserve da capitale", False, "67988652.23", "67988652.23"),
    ("III", "A.III) Risultato economico dell'esercizio", False, "-1609071.73", "-1169084.42"),
    ("IV", "A.IV) Risultati economici di esercizi precedenti", False, "-1169084.42", "0"),
    ("", "TOTALE PATRIMONIO NETTO (A)", True, "168530677.94", "170139749.67"),
    ("2", "D.2) Debiti verso fornitori", False, "2746010.96", "24358006.01"),
    ("4", "D.4) Debiti per trasferimenti e contributi", False, "351064.73", "1089649.49"),
    ("5", "D.5) Altri debiti", False, "1088243.87", "2188847.54"),
    ("", "TOTALE DEBITI (D)", True, "4185319.56", "27636503.04"),
    ("I", "E.I) Ratei passivi", False, "38918.59", "58507.67"),
    ("II", "E.II) Risconti passivi (contributi agli investimenti)", False, "87911371.47", "88544663.40"),
    ("", "TOTALE RATEI E RISCONTI (E)", True, "87950290.06", "88603171.07"),
    ("", "TOTALE DEL PASSIVO (A+B+C+D+E)", True, "260666287.56", "286379423.78"),
]

_CONTO_ECONOMICO: list[tuple[str, str, bool, str, str]] = [
    ("3", "A.3) Proventi da trasferimenti e contributi", False, "2768286.37", "2695982.00"),
    ("4", "A.4) Ricavi delle vendite e prestazioni e proventi da servizi pubblici", False, "2798926.48", "2785538.14"),
    ("8", "A.8) Altri ricavi e proventi diversi", False, "1948753.77", "1715923.70"),
    ("", "TOTALE COMPONENTI POSITIVI DELLA GESTIONE (A)", True, "7515966.62", "7197443.84"),
    ("9", "B.9) Acquisto di materie prime e/o beni di consumo", False, "5375.76", "5570.58"),
    ("10", "B.10) Prestazioni di servizi", False, "3067269.17", "2273739.14"),
    ("11", "B.11) Utilizzo beni di terzi", False, "1298.50", "1549.47"),
    ("12", "B.12) Trasferimenti e contributi", False, "730239.48", "1122804.48"),
    ("13", "B.13) Personale", False, "474909.91", "745687.44"),
    ("14", "B.14) Ammortamenti e svalutazioni", False, "4865153.07", "4490489.24"),
    ("18", "B.18) Oneri diversi di gestione", False, "184426.14", "161266.01"),
    ("", "TOTALE COMPONENTI NEGATIVI DELLA GESTIONE (B)", True, "-9328672.03", "-8801106.36"),
    ("", "DIFFERENZA FRA COMPONENTI POSITIVI E NEGATIVI DELLA GESTIONE (A-B)", True, "-1812705.41", "-1603662.52"),
    ("20", "C.20) Altri proventi finanziari", False, "77772.01", "28089.06"),
    ("", "TOTALE PROVENTI ED ONERI FINANZIARI (C)", True, "77772.01", "28089.06"),
    ("24", "E.24) Proventi straordinari", False, "190611.74", "1345694.66"),
    ("25", "E.25) Oneri straordinari", False, "-35224.51", "-907067.37"),
    ("", "TOTALE PROVENTI ED ONERI STRAORDINARI (E)", True, "155387.23", "438627.29"),
    ("", "RISULTATO PRIMA DELLE IMPOSTE (A-B+C+D+E)", True, "-1579546.17", "-1136946.17"),
    ("26", "26) Imposte", False, "-29525.56", "-32138.25"),
    ("", "27) RISULTATO DELL'ESERCIZIO", True, "-1609071.73", "-1169084.42"),
]


def curated_items(_fasc=None) -> list[es.StatementItem]:
    """Return the full curated CIT dataset as ``StatementItem`` rows."""
    items: list[es.StatementItem] = []
    cat_rows = {
        es.ATTIVO: _ATTIVO,
        es.PASSIVO: _PASSIVO,
        es.CONTO_ECONOMICO: _CONTO_ECONOMICO,
    }
    for category, rows in cat_rows.items():
        for seq, (code, name, is_tot, v_cur, v_prev) in enumerate(rows):
            for yr, raw in ((YEAR_CUR, v_cur), (YEAR_PREV, v_prev)):
                items.append(es.StatementItem(
                    category=category, seq=seq, code=code, name=name, year=yr,
                    value=Decimal(raw), is_total=is_tot,
                    related_party=None, source_page=0))
    return items
