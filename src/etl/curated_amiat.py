"""Hand-curated AMIAT statements, transcribed directly from *Bilancio Amiat 2024.pdf*.

AMIAT S.p.A. (waste collection for the City of Turin, now in the Iren group)
publishes a single IAS/IFRS *bilancio d'esercizio* (no consolidato). Its
prospetti carry the usual "di cui parti correlate" columns and spaced/garbled
figures that defeat the generic parser, so the figures are transcribed by hand
and the quadratura verified.

Source pages (1-based, as printed in the PDF):
  * 41 — Prospetto della situazione patrimoniale-finanziaria (Attività + PN/Passività)
  * 42 — Prospetto di conto economico
  * 95 — Dettaglio rapporti con parti correlate (riga «Comune Torino»)

Amounts are in **full euros**. As in the IFRS prospetto, operating costs,
ammortamenti, oneri finanziari and imposte are printed in parentheses
(negative). The related-party detail (p.95) is a single 31.12.2024 snapshot;
the City of Turin is AMIAT's main customer (≈186M EUR of revenue).
"""

from __future__ import annotations

from decimal import Decimal

from src.normalization import entity_statements as es

SOURCE_DOCUMENT = "Bilancio Amiat 2024.pdf"

YEAR_CUR = 2024
YEAR_PREV = 2023

# (name, is_total, value_2024, value_2023) — in euros.
_ATTIVO: list[tuple[str, bool, int, int]] = [
    ("Attività materiali", False, 164_992_247, 156_879_633),
    ("Attività immateriali a vita definita", False, 8_514_417, 9_192_327),
    ("Altre partecipazioni", False, 8_079_104, 8_079_104),
    ("Attività finanziarie non correnti", False, 0, 0),
    ("Crediti commerciali non correnti", False, 15_803_598, 14_015_948),
    ("Altre attività non correnti", False, 83_225, 115_294),
    ("Attività per imposte anticipate", False, 4_091_449, 4_047_138),
    ("TOTALE ATTIVITA' NON CORRENTI", True, 201_564_040, 192_329_445),
    ("Rimanenze", False, 815_255, 540_341),
    ("Crediti commerciali", False, 45_153_428, 18_697_966),
    ("Crediti per imposte correnti", False, 17_836, 259_872),
    ("Crediti vari e altre attività correnti", False, 3_873_673, 5_543_542),
    ("Attività finanziarie correnti", False, 533_525, 196_632),
    ("Disponibilità liquide e mezzi equivalenti", False, 0, 0),
    ("TOTALE ATTIVITA' CORRENTI", True, 50_393_717, 25_238_354),
    ("Attività destinate ad esser cedute", False, 0, 0),
    ("TOTALE ATTIVITA'", True, 251_957_757, 217_567_799),
]

_PASSIVO: list[tuple[str, bool, int, int]] = [
    ("Capitale sociale", False, 46_326_462, 46_326_462),
    ("Riserve e Utili (Perdite) a nuovo", False, 35_004_415, 34_799_746),
    ("Risultato netto del periodo", False, 3_371_366, 5_088_380),
    ("TOTALE PATRIMONIO NETTO", True, 84_702_243, 86_214_588),
    ("Passività finanziarie non correnti", False, 81_521_389, 47_238_486),
    ("Benefici ai dipendenti", False, 9_243_181, 10_228_355),
    ("Fondi per rischi ed oneri", False, 10_864_509, 11_014_265),
    ("Debiti vari e altre passività non correnti", False, 1_564_362, 1_882_548),
    ("TOTALE PASSIVITA' NON CORRENTI", True, 103_193_441, 70_363_653),
    ("Passività finanziarie correnti", False, 868_170, 708_379),
    ("Debiti commerciali", False, 47_104_793, 44_085_154),
    ("Debiti vari e altre passività correnti", False, 16_089_111, 16_196_025),
    ("Debiti per imposte correnti", False, 0, 0),
    ("Fondi rischi ed oneri quota corrente", False, 0, 0),
    ("TOTALE PASSIVITA' CORRENTI", True, 64_062_074, 60_989_557),
    ("Passività correlate ad attività destinate ad essere cedute", False, 0, 0),
    ("TOTALE PASSIVITA'", True, 167_255_514, 131_353_211),
    ("TOTALE PATRIMONIO NETTO E PASSIVITA'", True, 251_957_757, 217_567_799),
]

_CONTO_ECONOMICO: list[tuple[str, bool, int, int]] = [
    ("Ricavi per beni e servizi", False, 217_349_210, 204_024_866),
    ("Altri proventi", False, 11_512_062, 11_899_218),
    ("Totale ricavi", True, 228_861_272, 215_924_084),
    ("Costi materie prime sussidiarie di consumo e merci", False, -9_359_155, -9_498_379),
    ("Prestazioni di servizi e godimento beni di terzi", False, -118_745_578, -110_350_025),
    ("Oneri diversi di gestione", False, -1_927_465, -1_899_571),
    ("Costi per lavori interni capitalizzati", False, 1_283_992, 1_088_616),
    ("Costo del personale", False, -75_839_378, -72_525_866),
    ("Totale costi operativi", True, -204_587_584, -193_185_224),
    ("MARGINE OPERATIVO LORDO", True, 24_273_688, 22_738_860),
    ("Ammortamenti", False, -17_752_658, -14_947_594),
    ("Accantonamenti e svalutazioni", False, 523_178, 1_123_936),
    ("Totale ammortamenti, accantonamenti e svalutazioni", True, -17_229_480, -13_823_658),
    ("RISULTATO OPERATIVO", True, 7_044_208, 8_915_202),
    ("Proventi finanziari", False, 429_971, 233_278),
    ("Oneri finanziari", False, -2_671_097, -2_011_596),
    ("Totale gestione finanziaria", True, -2_241_126, -1_778_318),
    ("Rettifica di valore di partecipazioni", False, 0, 0),
    ("Risultato prima delle imposte", True, 4_803_082, 7_136_884),
    ("Imposte sul reddito", False, -1_431_716, -2_048_504),
    ("Risultato netto delle attività in continuità", True, 3_371_366, 5_088_380),
    ("Risultato netto da attività operative cessate", False, 0, 0),
    ("Risultato netto del periodo", True, 3_371_366, 5_088_380),
]

# Related-party detail with «Comune Torino» (p.95), 2024 snapshot, euros.
# (category, name, value)
_RAPPORTI_TORINO: list[tuple[str, str, int]] = [
    (es.ATTIVO,  "Crediti commerciali verso Città di Torino", 43_671_232),
    (es.PASSIVO, "Debiti commerciali verso Città di Torino", 160),
    (es.CONTO_ECONOMICO, "Ricavi e proventi da Città di Torino", 185_824_067),
    (es.CONTO_ECONOMICO, "Costi e altri oneri verso Città di Torino", 666_316),
    (es.CONTO_ECONOMICO, "Proventi finanziari da Città di Torino", 276_705),
]


def curated_items(_fasc=None) -> list[es.StatementItem]:
    """Return the full curated AMIAT dataset as ``StatementItem`` rows."""
    items: list[es.StatementItem] = []

    cat_pages = {
        es.ATTIVO: (_ATTIVO, 41),
        es.PASSIVO: (_PASSIVO, 41),
        es.CONTO_ECONOMICO: (_CONTO_ECONOMICO, 42),
    }
    rapporti_seq = {es.ATTIVO: 0, es.PASSIVO: 0, es.CONTO_ECONOMICO: 0}
    for category, (rows, page) in cat_pages.items():
        for seq, (name, is_tot, v_cur, v_prev) in enumerate(rows):
            for yr, val in ((YEAR_CUR, v_cur), (YEAR_PREV, v_prev)):
                items.append(es.StatementItem(
                    category=category, seq=seq, code="", name=name, year=yr,
                    value=Decimal(val), is_total=is_tot,
                    related_party=None, source_page=page))
        rapporti_seq[category] = len(rows)

    # Related-party detail (only 2024, page 95, flagged as «socio»).
    for category, name, val in _RAPPORTI_TORINO:
        seq = rapporti_seq[category]
        rapporti_seq[category] += 1
        items.append(es.StatementItem(
            category=category, seq=seq, code="", name=name, year=YEAR_CUR,
            value=Decimal(val), is_total=False,
            related_party="socio", source_page=95))

    return items
