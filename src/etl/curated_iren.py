"""Hand-curated IREN consolidated statements (Gruppo Iren), transcribed directly
from the *Relazione Annuale Integrata 2024* PDF.

We do NOT parse IREN with the coordinate-based normalizer: the consolidated
prospetti carry footnotes, multi-line labels and a "di cui parti correlate"
column that the generic parser misreads (footnote text picked up as a value,
labels truncated). Since every partecipata's PDF has a different layout, the
pragmatic choice for the handful of entities we care about is to transcribe the
figures once, by hand, and verify the quadratura.

Source pages (1-based, as printed in the PDF):
  * 306 — Situazione patrimoniale-finanziaria · Attività
  * 307 — Situazione patrimoniale-finanziaria · Patrimonio netto e Passività
  * 308 — Conto economico
  * 412-413 — Dettaglio rapporti con parti correlate (riga «Comune Torino»)

All amounts on the prospetti are in *migliaia di euro*; we store full euros
(×1000). Costs/negatives are entered with their sign. The related-party detail
(pp.412-413) is a single snapshot at 31.12.2024.
"""

from __future__ import annotations

from decimal import Decimal

from src.normalization import entity_statements as es

SOURCE_DOCUMENT = "Relazione Annuale Integrata 2024.pdf"
_K = 1000  # migliaia → euro

YEAR_CUR = 2024
YEAR_PREV = 2023

# (name, is_total, value_2024, value_2023) — in migliaia di euro.
_ATTIVO: list[tuple[str, bool, int, int]] = [
    ("Immobili impianti e macchinari", False, 4_516_355, 4_460_852),
    ("Investimenti immobiliari", False, 1_974, 2_031),
    ("Attività immateriali a vita definita", False, 3_357_523, 3_140_359),
    ("Avviamento", False, 247_273, 244_977),
    ("Partecipazioni contabilizzate con il metodo del Patrimonio Netto", False, 282_462, 212_798),
    ("Altre partecipazioni", False, 8_723, 10_914),
    ("Attività derivanti da contratti con i clienti non correnti", False, 300_238, 232_384),
    ("Crediti commerciali non correnti", False, 33_840, 29_416),
    ("Attività finanziarie non correnti", False, 124_756, 128_937),
    ("Altre attività non correnti", False, 131_668, 163_992),
    ("Attività per imposte anticipate", False, 389_533, 400_092),
    ("Totale attività non correnti", True, 9_394_345, 9_026_752),
    ("Rimanenze", False, 84_033, 73_877),
    ("Attività derivanti da contratti con i clienti correnti", False, 69_291, 29_830),
    ("Crediti commerciali", False, 1_442_454, 1_288_107),
    ("Attività per imposte correnti", False, 14_474, 18_894),
    ("Crediti vari e altre attività correnti", False, 298_717, 576_516),
    ("Attività finanziarie correnti", False, 580_646, 242_184),
    ("Disponibilità liquide e mezzi equivalenti", False, 326_568, 436_134),
    ("Attività possedute per la vendita", False, 790, 1_144),
    ("Totale attività correnti", True, 2_816_973, 2_666_686),
    ("TOTALE ATTIVITA'", True, 12_211_318, 11_693_438),
]

_PASSIVO: list[tuple[str, bool, int, int]] = [
    ("Capitale sociale", False, 1_300_931, 1_300_931),
    ("Riserve e Utili (Perdite) a nuovo", False, 1_306_622, 1_250_525),
    ("Risultato netto del periodo", False, 268_471, 254_752),
    ("Totale patrimonio netto attribuibile agli azionisti della controllante", True, 2_876_024, 2_806_208),
    ("Patrimonio netto attribuibile alle minoranze", False, 467_673, 438_086),
    ("TOTALE PATRIMONIO NETTO", True, 3_343_697, 3_244_294),
    ("Passività finanziarie non correnti", False, 4_460_916, 4_048_316),
    ("Benefici ai dipendenti", False, 81_495, 87_329),
    ("Fondi per rischi ed oneri", False, 276_258, 404_882),
    ("Passività per imposte differite", False, 116_857, 130_532),
    ("Debiti vari e altre passività non correnti", False, 751_559, 581_844),
    ("Totale passività non correnti", True, 5_687_085, 5_252_903),
    ("Passività finanziarie correnti", False, 656_530, 736_379),
    ("Debiti commerciali", False, 1_787_198, 1_634_720),
    ("Passività derivanti da contratti con i clienti correnti", False, 88_983, 79_642),
    ("Debiti vari e altre passività correnti", False, 353_693, 333_182),
    ("Debiti per imposte correnti", False, 12_743, 80_437),
    ("Fondi per rischi ed oneri quota corrente", False, 281_389, 331_881),
    ("Passività correlate ad attività possedute per la vendita", False, 0, 0),
    ("Totale passività correnti", True, 3_180_536, 3_196_241),
    ("TOTALE PASSIVITA'", True, 8_867_621, 8_449_144),
    ("TOTALE PATRIMONIO NETTO E PASSIVITA'", True, 12_211_318, 11_693_438),
]

_CONTO_ECONOMICO: list[tuple[str, bool, int, int]] = [
    ("Ricavi per beni e servizi", False, 5_903_454, 6_301_581),
    ("Altri proventi", False, 139_671, 188_800),
    ("Totale ricavi", True, 6_043_125, 6_490_381),
    ("Costi materie prime sussidiarie di consumo e merci", False, -2_224_054, -2_763_473),
    ("Prestazioni di servizi e godimento beni di terzi", False, -1_860_883, -1_876_663),
    ("Oneri diversi di gestione", False, -102_657, -113_865),
    ("Costi per lavori interni capitalizzati", False, 60_193, 56_907),
    ("Costo del personale", False, -641_605, -596_391),
    ("Totale costi operativi", True, -4_769_006, -5_293_485),
    ("MARGINE OPERATIVO LORDO", True, 1_274_119, 1_196_896),
    ("Ammortamenti", False, -655_475, -600_929),
    ("Accantonamenti a fondo svalutazione crediti", False, -74_482, -71_471),
    ("Altri accantonamenti e svalutazioni", False, -24_462, -60_108),
    ("Totale ammortamenti, accantonamenti e svalutazioni", True, -754_419, -732_508),
    ("RISULTATO OPERATIVO", True, 519_700, 464_388),
    ("Proventi finanziari", False, 45_701, 37_148),
    ("Oneri finanziari", False, -136_333, -135_781),
    ("Totale gestione finanziaria", True, -90_632, -98_633),
    ("Rettifica di valore di partecipazioni", False, -1_260, 6_263),
    ("Risultato di partecipazioni contabilizzate con il metodo del patrimonio netto al netto degli effetti fiscali", False, 7_471, 6_836),
    ("Risultato prima delle imposte", True, 435_279, 378_854),
    ("Imposte sul reddito", False, -131_697, -97_025),
    ("Risultato netto delle attività in continuità", True, 303_582, 281_829),
    ("Risultato netto da attività operative cessate", False, 0, 0),
    ("Risultato netto del periodo", True, 303_582, 281_829),
    ("- di cui attribuibile agli azionisti della controllante", False, 268_471, 254_752),
    ("- di cui attribuibile alle minoranze", False, 35_111, 27_077),
]

# Related-party detail with «Comune Torino» (pp.412-413), 2024 snapshot, migliaia.
# (category, name, value)
_RAPPORTI_TORINO: list[tuple[str, str, int]] = [
    (es.ATTIVO,  "Crediti commerciali verso Comune di Torino", 80_498),
    (es.ATTIVO,  "Crediti finanziari e disponibilità verso Comune di Torino", 36_232),
    (es.ATTIVO,  "Crediti di altra natura verso Comune di Torino", 83),
    (es.PASSIVO, "Debiti commerciali verso Comune di Torino", 2_593),
    (es.PASSIVO, "Debiti finanziari verso Comune di Torino", 6_068),
    (es.CONTO_ECONOMICO, "Ricavi e altri proventi da Comune di Torino", 238_602),
    (es.CONTO_ECONOMICO, "Costi e altri oneri verso Comune di Torino", 6_482),
    (es.CONTO_ECONOMICO, "Proventi finanziari da Comune di Torino", 283),
    (es.CONTO_ECONOMICO, "Oneri finanziari verso Comune di Torino", 10),
]


def curated_items(_fasc=None) -> list[es.StatementItem]:
    """Return the full curated IREN dataset as ``StatementItem`` rows."""
    items: list[es.StatementItem] = []

    # Main prospetti: both years, related_party None.
    cat_pages = {
        es.ATTIVO: (_ATTIVO, 306),
        es.PASSIVO: (_PASSIVO, 307),
        es.CONTO_ECONOMICO: (_CONTO_ECONOMICO, 308),
    }
    rapporti_seq = {es.ATTIVO: 0, es.PASSIVO: 0, es.CONTO_ECONOMICO: 0}
    for category, (rows, page) in cat_pages.items():
        for seq, (name, is_tot, v_cur, v_prev) in enumerate(rows):
            for yr, val in ((YEAR_CUR, v_cur), (YEAR_PREV, v_prev)):
                items.append(es.StatementItem(
                    category=category, seq=seq, code="", name=name, year=yr,
                    value=Decimal(val * _K), is_total=is_tot,
                    related_party=None, source_page=page))
        rapporti_seq[category] = len(rows)

    # Related-party detail (only 2024, on its own pages, flagged as «socio»).
    rp_page = {es.ATTIVO: 412, es.PASSIVO: 412, es.CONTO_ECONOMICO: 413}
    for category, name, val in _RAPPORTI_TORINO:
        seq = rapporti_seq[category]
        rapporti_seq[category] += 1
        items.append(es.StatementItem(
            category=category, seq=seq, code="", name=name, year=YEAR_CUR,
            value=Decimal(val * _K), is_total=False,
            related_party="socio", source_page=rp_page[category]))

    return items
