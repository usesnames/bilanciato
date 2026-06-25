"""Hand-curated SMAT consolidated statements (Gruppo SMAT), transcribed directly
from *BILANCIO-SMAT-31-12-2024-light.pdf*.

Like IREN, SMAT's consolidated prospetti are IAS/IFRS and too irregular for the
generic coordinate parser (multi-line totals, a truncated «di terzi» label, the
"Altre spese operative" values printed out of order). The figures are therefore
transcribed by hand and the quadratura verified.

Source pages (1-based, as printed in the PDF):
  * 149 — Situazione patrimoniale-finanziaria consolidata · Attività
  * 150 — Situazione patrimoniale-finanziaria consolidata · Patrimonio netto e Passività
  * 151 — Conto economico consolidato
  * 192 — Dettaglio rapporti con parti correlate (riga «CITTÀ DI TORINO»)

Amounts are in **full euros** (the SMAT prospetti are not in migliaia). Costs
and negatives are entered with the sign printed in the PDF: operating costs are
shown positive (MOL = ricavi − costi operativi), while ammortamenti, oneri
finanziari, imposte and the FTA reserve are printed in parentheses (negative).
The related-party detail (p.192) is a single snapshot at 31.12.2024.
"""

from __future__ import annotations

from decimal import Decimal

from src.normalization import entity_statements as es

SOURCE_DOCUMENT = "BILANCIO-SMAT-31-12-2024-light.pdf"

YEAR_CUR = 2024
YEAR_PREV = 2023

# (name, is_total, value_2024, value_2023) — in euros.
_ATTIVO: list[tuple[str, bool, int, int]] = [
    ("Immobilizzazioni materiali", False, 154_801_652, 140_958_398),
    ("Avviamento", False, 0, 5_928_005),
    ("Altre immobilizzazioni immateriali", False, 3_669_670, 2_999_513),
    ("Beni in concessione", False, 1_049_011_861, 884_673_089),
    ("Partecipazioni", False, 11_814_577, 11_662_906),
    ("Attività fiscali differite", False, 26_357_031, 23_838_381),
    ("Attività finanziarie non correnti", False, 1_429_294, 1_408_035),
    ("Altre attività non correnti", False, 0, 0),
    ("Totale attività non correnti", True, 1_247_084_085, 1_071_468_327),
    ("Rimanenze", False, 9_578_420, 9_516_760),
    ("Crediti commerciali", False, 260_858_964, 239_759_196),
    ("Attività fiscali correnti", False, 489_446, 5_473_320),
    ("Attività finanziarie correnti", False, 12_958, 19_438),
    ("Altre attività correnti", False, 7_476_962, 8_463_571),
    ("Disponibilità liquide e mezzi equivalenti", False, 77_585_621, 111_455_195),
    ("Totale attività correnti", True, 356_002_371, 374_687_480),
    ("Attività destinate alla vendita", False, 0, 0),
    ("TOTALE ATTIVITÀ", True, 1_603_086_456, 1_446_155_807),
]

_PASSIVO: list[tuple[str, bool, int, int]] = [
    ("Capitale Sociale", False, 345_533_762, 345_533_762),
    ("Riserva legale", False, 29_960_114, 27_887_553),
    ("Riserva vincolata attuazione PEF", False, 376_447_796, 344_944_872),
    ("Riserva FTA", False, -2_845_993, -2_845_993),
    ("Altre riserve e risultati a nuovo", False, 5_388_770, 5_103_871),
    ("Risultato d'esercizio di competenza degli azionisti della Capogruppo", False, 32_631_910, 41_613_345),
    ("TOTALE PATRIMONIO NETTO DELLA CAPOGRUPPO", True, 787_116_359, 762_237_410),
    ("Altre riserve di competenza di terzi", False, 406_876, 465_092),
    ("Risultato d'esercizio di competenza di terzi", False, 38_652, 90_173),
    ("TOTALE PATRIMONIO NETTO DI TERZI", True, 445_528, 555_265),
    ("TOTALE PATRIMONIO NETTO", True, 787_561_887, 762_792_675),
    ("Passività finanziarie non correnti", False, 416_114_432, 253_089_707),
    ("Fondo TFR e altri benefici", False, 9_541_137, 9_860_193),
    ("Fondi per rischi ed oneri", False, 20_041_888, 18_971_220),
    ("Passività per imposte differite", False, 2_977_084, 292_530),
    ("Altre passività non correnti", False, 114_185_650, 84_820_535),
    ("Totale passività non correnti", True, 562_860_191, 367_034_185),
    ("Passività finanziarie correnti", False, 39_849_621, 139_406_877),
    ("Debiti commerciali", False, 137_103_527, 102_661_767),
    ("Passività per imposte correnti", False, 7_078_542, 3_699_552),
    ("Altre passività correnti", False, 68_632_688, 70_560_751),
    ("Altre passività finanziarie", False, 0, 0),
    ("Totale passività correnti", True, 252_664_378, 316_328_947),
    ("Passività destinate alla vendita", False, 0, 0),
    ("TOTALE PASSIVITÀ", True, 815_524_569, 683_363_132),
    ("TOTALE PATRIMONIO NETTO E PASSIVITÀ", True, 1_603_086_456, 1_446_155_807),
]

_CONTO_ECONOMICO: list[tuple[str, bool, int, int]] = [
    ("Ricavi", False, 376_260_329, 371_063_942),
    ("Ricavi per attività di progettazione e costruzione", False, 227_080_414, 107_102_379),
    ("Altri ricavi operativi", False, 25_357_258, 27_512_771),
    ("Totale ricavi", True, 628_698_001, 505_679_092),
    ("Consumi di materie prime e materiali di consumo", False, 20_031_369, 19_060_225),
    ("Costi per servizi e godimento beni", False, 142_330_625, 147_152_352),
    ("Costi del personale", False, 66_087_954, 63_230_959),
    ("Altre spese operative", False, 26_840_897, 25_076_045),
    ("Costi per attività di progettazione e costruzione", False, 221_729_304, 103_137_269),
    ("Totale costi operativi", True, 477_020_149, 357_656_850),
    ("Margine Operativo Lordo", True, 151_677_852, 148_022_242),
    ("Ammortamenti, accantonamenti e svalutazioni", False, -105_630_820, -95_222_613),
    ("Risultato Operativo (EBIT)", True, 46_047_032, 52_799_629),
    ("Proventi finanziari", False, 10_837_796, 9_782_811),
    ("Oneri finanziari", False, -10_601_189, -7_782_560),
    ("Totale gestione finanziaria", True, 236_607, 2_000_251),
    ("Risultato al lordo delle imposte", True, 46_283_639, 54_799_880),
    ("Imposte", False, -13_613_077, -13_096_362),
    ("RISULTATO NETTO D'ESERCIZIO", True, 32_670_562, 41_703_518),
    ("- di cui di competenza di azionisti terzi", False, 38_652, 90_173),
    ("- di cui di competenza della capogruppo", False, 32_631_910, 41_613_345),
]

# Related-party detail with «Città di Torino» (p.192), 2024 snapshot, euros.
# (category, name, value)
_RAPPORTI_TORINO: list[tuple[str, str, int]] = [
    (es.ATTIVO,  "Crediti commerciali verso Città di Torino", 1_470_897),
    (es.PASSIVO, "Debiti commerciali verso Città di Torino", 763_218),
    (es.CONTO_ECONOMICO, "Ricavi da Città di Torino", 4_514_095),
    (es.CONTO_ECONOMICO, "Costi operativi verso Città di Torino", 1_917_424),
]


def curated_items(_fasc=None) -> list[es.StatementItem]:
    """Return the full curated SMAT consolidated dataset as ``StatementItem`` rows."""
    items: list[es.StatementItem] = []

    cat_pages = {
        es.ATTIVO: (_ATTIVO, 149),
        es.PASSIVO: (_PASSIVO, 150),
        es.CONTO_ECONOMICO: (_CONTO_ECONOMICO, 151),
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

    # Related-party detail (only 2024, page 192, flagged as «socio»).
    for category, name, val in _RAPPORTI_TORINO:
        seq = rapporti_seq[category]
        rapporti_seq[category] += 1
        items.append(es.StatementItem(
            category=category, seq=seq, code="", name=name, year=YEAR_CUR,
            value=Decimal(val), is_total=False,
            related_party="socio", source_page=192))

    return items
