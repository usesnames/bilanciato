"""Tests for the analytic rendiconto per-capitoli layer.

Pure-function tests over the multi-line/label-collision parser (including that
subtotal blocks are skipped and entrate's duplicated CP/CS/TR labels are
disambiguated by order), plus a DB regression that the capitoli reconcile to the
per-missione/per-titolo aggregates.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.dashboard.glossary import capitolo_note
from src.normalization.rendiconto_capitoli import normalize_capitoli


def test_capitolo_note_art195_both_sides():
    sp = capitolo_note("USCITE DERIVANTI DALLA GESTIONE DEGLI INCASSI VINCOLATI "
                       "DEGLI ENTI LOCALI - UTILIZZO INCASSI VINCOLATI AI SENSI "
                       "DELL'ART. 195 DEL TUEL - settore 024")
    en = capitolo_note("ENTRATE DERIVANTI DALLA GESTIONE DEGLI INCASSI VINCOLATI "
                       "DEGLI ENTI LOCALI - REINTEGRO INCASSI VINCOLATI AI SENSI "
                       "DELL'ART. 195 DEL TUEL - settore 024")
    reg = capitolo_note("ENTRATE PER REGOLARIZZAZIONE CASSA VINCOLATA A SEGUITO "
                        "DI ERRONEA IMPUTAZIONE - SET. 024")
    assert sp and "non è una vera spesa" in sp[0]
    assert en and "non è una vera entrata" in en[0]
    assert reg and "non è una vera entrata" in reg[0]
    assert capitolo_note("STIPENDI PERSONALE DI RUOLO") is None
    assert capitolo_note(None) is None
from src.utils.config import DB_PATH

# Two spese capitoli (the second with a wrapped denominazione) followed by a
# macroaggregato subtotal that the parser must NOT count as a capitolo.
_SPESE = """\
COMUNE DI TORINO Conto di Bilancio D.Lgs 118 analitico (Multilingua) - spese per Titoli - SPESE (anno 2023)
TITOLO 1: Spese correnti
MISSIONE 1: Servizi istituzionali, generali e di gestione
PROGRAMMA 1: Organi istituzionali
MACROAGGREGATO 1: Redditi da lavoro dipendente
1 1 1 1 002900000001GABINETTO DEL SINDACO - RETRIBUZIONI - settore 004 RS 350.399,06 PR 350.399,06 R 0,00 EP 0,00
CP 2.458.790,40 PC 2.117.582,07 I 2.458.790,40 ECP -1.174.634,42 EC 341.208,33
CS 3.413.083,80 TP 2.467.981,13 FPV 1.174.634,42 TR 341.208,33
1 1 1 1 002900000007GABINETTO DEL SINDACO - COMPETENZE - RS 0,00 PR 0,00 R 0,00 EP 0,00
settore 004
CP 8.020.477,21 PC 8.015.209,80 I 8.015.209,80 ECP -468.875,38 EC 0,00
CS 8.494.620,00 TP 8.015.209,80 FPV 474.142,79 TR 0,00
TOTALE MACROAGGREGATO 1: Redditi da lavoro dipendente RS 350.399,06 PR 350.399,06 R 0,00 EP 0,00
CP 10.479.267,61 PC 10.132.791,87 I 10.474.000,20 ECP -1.643.509,80 EC 341.208,33
CS 11.907.703,80 TP 10.483.190,93 FPV 1.648.777,21 TR 341.208,33
"""

_ENTRATE = """\
COMUNE DI TORINO Conto di Bilancio D.Lgs 118 analitico (Multilingua) - spese per Titoli - ENTRATE (anno 2023)
TITOLO 1: Entrate correnti di natura tributaria, contributiva e perequativa
TIPOLOGIA 101: Imposte, tasse e proventi assimilati
CATEGORIA 6: Imposta municipale propria
1 101 6 000100000001 IMPOSTA MUNICIPALE PROPRIA - IMU - settore 013 RS 5.500.000,00 RR 5.500.000,00 R 0,00 EP 0,00
CP 269.000.000,00 RC 248.884.517,87 A 255.190.301,98 CP -13.809.698,02 EC 6.305.784,11
CS 274.500.000,00 TR 254.384.517,87 CS -20.115.482,13 TR 6.305.784,11
"""


def _by_measure(items):
    return {(it.capitolo_code, it.measure): it.value for it in items}


def test_spese_two_capitoli_subtotal_skipped():
    items = normalize_capitoli([(1, _SPESE)])
    caps = {it.capitolo_code for it in items}
    assert caps == {"002900000001", "002900000007"}  # the subtotal is NOT a capitolo
    impegni = sum(it.value for it in items if it.measure == "impegni")
    assert impegni == Decimal("10474000.20")  # == the printed subtotal, not doubled


def test_spese_hierarchy_and_denominazione():
    items = normalize_capitoli([(1, _SPESE)])
    first = next(it for it in items if it.capitolo_code == "002900000001")
    assert first.kind == "spesa"
    assert first.liv1_code == "01" and "Servizi istituzionali" in first.liv1_name
    assert first.liv2_code == "1" and first.liv3_code == "1"
    assert first.sezione == "Spese correnti"
    assert "GABINETTO DEL SINDACO" in first.denominazione
    # value labels must not leak into the denominazione
    assert "RS" not in first.denominazione and "CP" not in first.denominazione
    # wrapped denominazione is reconstructed
    second = next(it for it in items if it.capitolo_code == "002900000007")
    assert "settore 004" in second.denominazione


def test_spese_core_measure_values():
    m = _by_measure(normalize_capitoli([(1, _SPESE)]))
    assert m[("002900000001", "previsioni")] == Decimal("2458790.40")
    assert m[("002900000001", "impegni")] == Decimal("2458790.40")
    assert m[("002900000001", "pagamenti_totali")] == Decimal("2467981.13")
    assert m[("002900000001", "fpv")] == Decimal("1174634.42")


# A capitolo whose block straddles a page break: the repeated footer + header band
# of the next page falls inside the block, plus an FPV (9-digit) row follows.
_PAGEBREAK = """\
COMUNE DI TORINO Conto di Bilancio D.Lgs 118 analitico (Multilingua) - spese per Titoli - SPESE (anno 2023)
TITOLO 2: Spese in conto capitale
MISSIONE 10: Trasporti e diritto alla mobilità
PROGRAMMA 5: Viabilità e infrastrutture stradali
MACROAGGREGATO 5: Altre spese in conto capitale
2 10 5 5 074100001001NETTEZZA URBANA - ALTRE SPESE - settore 064 RS 0,00 PR 0,00 R 0,00 EP 0,00
CP 1.000,00 PC 0,00 I 1.000,00 ECP 0,00 EC 0,00
Data di stampa: 06/03/2025 Pagina 318 di540
COMUNE DI TORINO Conto di Bilancio D.Lgs 118 analitico (Multilingua) - spese per Titoli - SPESE (anno 2023)
.RGGAORCAM
CODICE
CAPITOLO
OLOTIT ENOISSIM
AMMARGORP RESIDUI PASSIVI AL 1/1/2023 PAGAMENTI IN C/RESIDUI (PR)RIACCERTAMENTI RESIDUI (R) RESIDUI PASSIVI DA ESERC.
(RS) PREC. (EP=RS-PR+R+P)
DENOMINAZIONE PREVISIONI DEFINITIVE DI PAGAMENTI IN IMPEGNI (I) ECONOMIE DI COMPETENZA
PREVISIONI DEFINITIVE DI TOTALE PAGAMENTI FONDO PLURIENNALE TOTALE RESIDUI PASSIVI DA
CASSA (CS) (TP=PR+PC) VINCOLATO (FPV) RIPORT. (TR=EP+EC)
CS 1.000,00 TP 0,00 FPV 0,00 TR 0,00
2 10 5 5 972510205 FPV - TRASPORTI - REALIZZAZIONE LINEA 2 METRO RS 0,00 PR 0,00 R 0,00 EP 0,00
CP 45.278.923,02 PC 0,00 I 0,00 ECP 45.278.923,02 EC 0,00
CS 0,00 TP 0,00 FPV 0,00 TR 0,00
"""


def test_pagebreak_boilerplate_and_fpv():
    items = normalize_capitoli([(1, _PAGEBREAK)])
    caps = {it.capitolo_code for it in items}
    # the 9-digit FPV placeholder row is NOT recorded as a capitolo
    assert caps == {"074100001001"}
    cap = next(it for it in items if it.measure == "impegni")
    # denominazione must be clean: no footer/header boilerplate, no FPV row glued in
    assert cap.denominazione == "NETTEZZA URBANA - ALTRE SPESE - settore 064"
    for junk in ("COMUNE DI TORINO", "Data di stampa", "DENOMINAZIONE", "RGGAORCAM", "FPV - TRASPORTI"):
        assert junk not in cap.denominazione
    # values survive the page break (the CS/TP line on the next page is captured)
    m = _by_measure(items)
    assert m[("074100001001", "impegni")] == Decimal("1000.00")
    assert m[("074100001001", "pagamenti_totali")] == Decimal("0.00")


def test_entrate_label_collisions_disambiguated():
    m = _by_measure(normalize_capitoli([(1, _ENTRATE)]))
    code = "000100000001"
    assert m[(code, "previsioni")] == Decimal("269000000.00")          # 1st CP
    assert m[(code, "accertamenti")] == Decimal("255190301.98")        # A
    assert m[(code, "maggiori_minori_accertamenti")] == Decimal("-13809698.02")  # 2nd CP
    assert m[(code, "previsioni_cassa")] == Decimal("274500000.00")    # 1st CS
    assert m[(code, "riscossioni_totali")] == Decimal("254384517.87")  # 1st TR
    assert m[(code, "maggiori_minori_cassa")] == Decimal("-20115482.13")  # 2nd CS
    assert m[(code, "residui_da_riportare")] == Decimal("6305784.11")  # 2nd TR


def test_entrate_hierarchy():
    items = normalize_capitoli([(1, _ENTRATE)])
    it = items[0]
    assert it.kind == "entrata"
    assert it.liv1_code == "1" and "tributaria" in it.liv1_name
    assert it.liv2_code == "101" and it.liv3_code == "6"
    assert it.sezione is None


@pytest.mark.skipif(not DB_PATH.exists(), reason="database not built")
def test_capitoli_reconcile_to_aggregate():
    from src.database.queries import Repository

    repo = Repository()
    try:
        if 2023 not in repo.capitoli_years():
            pytest.skip("per-capitoli file not ingested")
        for kind, measure in [("spesa", "impegni"), ("entrata", "accertamenti")]:
            tot = repo.rendiconto_total(kind=kind, measure=measure, year=2023)
            cap = repo.capitoli(kind=kind, year=2023, measure=measure, limit=100000)
            s = sum(float(r["value"]) for r in cap)
            assert abs(s - float(tot["value"])) < 1.0, f"{kind}/{measure} mismatch"
    finally:
        repo.close()
