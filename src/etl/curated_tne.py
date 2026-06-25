"""Hand-curated TNE statements, transcribed from *Torino_Nuova_Economia_Bilancio
2024_approvato.pdf* (deposited XBRL bilancio, schema civilistico).

Torino Nuova Economia S.p.A. owns the ex-Fiat "Mirafiori" site. It is held
48,86% by Finanziaria Città di Torino Holding S.p.A. (FCT Holding, the City's
wholly-owned vehicle), with Finpiemonte and a private shareholder. 2024 carries
a large loss (≈ -10,5M EUR), driven by the disposal of the «terreni e
fabbricati» and a 7M EUR write-down to the environmental-risk fund.

Source pages (1-based): SP pp.3-4, CE p.5, related-party note p.29.
Amounts in full euros. Costs in section B are entered positive; the
"Totale costi della produzione (B)" is negative (same convention as
INFRA.TO / FCT), so Differenza A-B = A + B.

The related-party line tagged «socio» is the debt toward FCT Holding
(Finanziaria Città di Torino) — financing 291.583 EUR + 9.572 EUR of interest —
i.e. TNE's exposure to the City's holding.
"""

from __future__ import annotations

from decimal import Decimal

from src.normalization import entity_statements as es

SOURCE_DOCUMENT = "Torino_Nuova_Economia_Bilancio 2024_approvato.pdf"

YEAR_CUR = 2024
YEAR_PREV = 2023

# (code, name, is_total, value_2024, value_2023) — euros.
_ATTIVO: list[tuple[str, str, bool, int, int]] = [
    ("1)", "B.II.1) Terreni e fabbricati", False, 0, 16_727_392),
    ("4)", "B.II.4) Altri beni", False, 597, 1_622),
    ("", "Totale immobilizzazioni materiali", True, 597, 16_729_014),
    ("", "Totale immobilizzazioni (B)", True, 597, 16_729_014),
    ("2)", "C.I.2) Prodotti in corso di lavorazione e semilavorati", False, 21_322_989, 24_759_704),
    ("5)", "C.I.5) Acconti", False, 0, 35_770),
    ("", "Totale rimanenze", True, 21_322_989, 24_795_474),
    ("1)", "C.II.1) Crediti verso clienti", False, 6_394, 1_695),
    ("5-bis)", "C.II.5-bis) Crediti tributari", False, 22_949, 31_608),
    ("5-quater)", "C.II.5-quater) Crediti verso altri", False, 1_055_322, 1_000_836),
    ("", "Totale crediti", True, 1_084_665, 1_034_139),
    ("1)", "C.IV.1) Depositi bancari e postali", False, 9_753_447, 712_194),
    ("3)", "C.IV.3) Danaro e valori in cassa", False, 43, 198),
    ("", "Totale disponibilità liquide", True, 9_753_490, 712_392),
    ("", "Totale attivo circolante (C)", True, 32_161_144, 26_542_005),
    ("D)", "D) Ratei e risconti attivi", False, 4_681, 3_823),
    ("", "Totale attivo", True, 32_166_422, 43_274_842),
]

_PASSIVO: list[tuple[str, str, bool, int, int]] = [
    ("", "A.I) Capitale", False, 54_270_424, 54_270_424),
    ("", "A.IV) Riserva legale", False, 228_012, 228_012),
    ("", "A.VI) Versamenti in conto futuro aumento di capitale", False, 8_936_777, 8_936_777),
    ("", "A.VI) Riserva da riduzione capitale sociale", False, 914_046, 914_046),
    ("", "Totale altre riserve", True, 9_850_823, 9_850_823),
    ("", "A.VIII) Utili (perdite) portati a nuovo", False, -28_560_475, -27_614_832),
    ("", "A.IX) Utile (perdita) dell'esercizio", False, -10_451_183, -945_643),
    ("", "Totale patrimonio netto", True, 25_337_601, 35_788_784),
    ("4)", "B.4) Fondi per rischi e oneri - altri", False, 3_717_123, 3_717_123),
    ("", "Totale fondi per rischi ed oneri", True, 3_717_123, 3_717_123),
    ("C)", "C) Trattamento di fine rapporto di lavoro subordinato", False, 162_976, 149_281),
    ("3)", "D.3) Debiti verso soci per finanziamenti", False, 1_542_863, 1_792_983),
    ("6)", "D.6) Acconti", False, 93_320, 0),
    ("7)", "D.7) Debiti verso fornitori", False, 87_731, 57_714),
    ("12)", "D.12) Debiti tributari", False, 716_884, 1_250_900),
    ("13)", "D.13) Debiti verso istituti di previdenza e di sicurezza sociale", False, 12_704, 11_447),
    ("14)", "D.14) Altri debiti", False, 125_000, 137_000),
    ("", "Totale debiti", True, 2_578_502, 3_250_044),
    ("E)", "E) Ratei e risconti passivi", False, 370_220, 369_610),
    ("", "Totale passivo", True, 32_166_422, 43_274_842),
]

_CONTO_ECONOMICO: list[tuple[str, str, bool, int, int]] = [
    ("1)", "A.1) Ricavi delle vendite e delle prestazioni", False, 500_193, 500_785),
    ("2)", "A.2) Variazioni delle rimanenze di prodotti in corso, semilavorati e finiti", False, -3_436_715, 0),
    ("5)", "A.5) Altri ricavi e proventi", False, 4_820, 79_493),
    ("", "Totale valore della produzione (A)", True, -2_931_702, 580_278),
    ("6)", "B.6) Per materie prime, sussidiarie, di consumo e di merci", False, 15_119, 3_902),
    ("7)", "B.7) Per servizi", False, 198_930, 563_233),
    ("8)", "B.8) Per godimento di beni di terzi", False, 18_484, 24_114),
    ("9)", "B.9) Per il personale", False, 279_216, 270_184),
    ("10)", "B.10) Ammortamenti e svalutazioni", False, 1_024, 337_754),
    ("12)", "B.12) Accantonamenti per rischi", False, 0, 50_000),
    ("14)", "B.14) Oneri diversi di gestione", False, 6_981_141, 215_707),
    ("", "Totale costi della produzione (B)", True, -7_493_914, -1_464_894),
    ("", "Differenza tra valore e costi della produzione (A-B)", True, -10_425_616, -884_616),
    ("", "C) Totale proventi e oneri finanziari (15+16-17+/-17bis)", True, -25_567, -61_027),
    ("", "Risultato prima delle imposte", True, -10_451_183, -945_643),
    ("21)", "21) Utile (perdita) dell'esercizio", True, -10_451_183, -945_643),
]

# Related-party detail with FCT Holding / Finanziaria Città di Torino (p.27/29),
# 2024 snapshot, euros. (category, name, value)
_RAPPORTI_TORINO: list[tuple[str, str, int]] = [
    (es.PASSIVO, "Debiti finanziari verso socio Finanziaria Città di Torino (FCT Holding)", 291_583),
    (es.CONTO_ECONOMICO, "Oneri finanziari verso socio Finanziaria Città di Torino (FCT Holding)", 9_572),
]


def curated_items(_fasc=None) -> list[es.StatementItem]:
    """Return the full curated TNE dataset as ``StatementItem`` rows."""
    items: list[es.StatementItem] = []

    cat_pages = {
        es.ATTIVO: (_ATTIVO, 3),
        es.PASSIVO: (_PASSIVO, 4),
        es.CONTO_ECONOMICO: (_CONTO_ECONOMICO, 5),
    }
    rapporti_seq = {es.ATTIVO: 0, es.PASSIVO: 0, es.CONTO_ECONOMICO: 0}
    for category, (rows, page) in cat_pages.items():
        for seq, (code, name, is_tot, v_cur, v_prev) in enumerate(rows):
            for yr, val in ((YEAR_CUR, v_cur), (YEAR_PREV, v_prev)):
                items.append(es.StatementItem(
                    category=category, seq=seq, code=code, name=name, year=yr,
                    value=Decimal(val), is_total=is_tot,
                    related_party=None, source_page=page))
        rapporti_seq[category] = len(rows)

    for category, name, val in _RAPPORTI_TORINO:
        seq = rapporti_seq[category]
        rapporti_seq[category] += 1
        items.append(es.StatementItem(
            category=category, seq=seq, code="", name=name, year=YEAR_CUR,
            value=Decimal(val), is_total=False,
            related_party="socio", source_page=29))

    return items
