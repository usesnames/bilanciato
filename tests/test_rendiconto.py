"""Tests for the rendiconto della gestione (conto del bilancio) layer.

Pure-function tests over the labelled-value parser plus the totals validator,
and a DB regression that the per-missione/per-titolo summaries are ingested and
reconcile to their printed grand totals.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.etl.validate import validate_rendiconto_totals
from src.normalization.rendiconto import (
    RendicontoItem,
    normalize_entrate,
    normalize_spese_missioni,
)
from src.utils.config import DB_PATH

# A faithful two-missione fragment of the RIEPILOGO SPESE PER MISSIONI, including
# the page-break header lines that the parser must ignore, plus the grand total.
_SPESE_TEXT = """\
Allegato n.10 - Rendiconto della gestione
CONTO DEL BILANCIO - RIEPILOGO GENERALE DELLE SPESE PER MISSIONI
DISAVANZO DI AMMINISTRAZIONE CP 25.353.849,72
Missione 01 Servizi istituzionali, generali e di gestione RS 54.390.287,04 PR 47.006.821,99 R -2.931.433,01 EP 4.452.032,04
CP 347.001.906,60 PC 229.285.790,22 I 274.018.862,88 ECP 33.532.180,58 EC 44.733.072,66
CS 391.297.786,31 TP 276.292.612,21 FPV 39.450.863,14 TR 49.185.104,70
Missione 02 Giustizia RS 338.361,10 PR 338.361,10 R 0,00 EP 0,00
CP 2.560.513,88 PC 1.399.892,59 I 1.731.776,90 ECP 30.033,26 EC 331.884,31
CS 2.467.068,42 TP 1.738.253,69 FPV 798.703,72 TR 331.884,31
TOTALE GENERALE DELLE SPESE RS 0,00 PR 0,00 R 0,00 EP 0,00
CP 349.562.420,48 PC 230.685.682,81 I 275.750.639,78 ECP 33.562.213,84 EC 45.064.956,97
CS 393.764.854,73 TP 278.030.865,90 FPV 40.249.566,86 TR 49.516.989,01
"""

# A titolo fragment of the RIEPILOGO GENERALE DELLE ENTRATE. Note CP and TR recur
# (previsioni / maggiori-minori, riscossioni / residui): the parser keeps the
# first occurrence of each label.
_ENTRATE_TEXT = """\
CONTO DEL BILANCIO - RIEPILOGO GENERALE DELLE ENTRATE
FONDO PLURIENNALE VINCOLATO PER SPESE CORRENTI CP 105.580.822,83
TITOLO 1: Entrate correnti di natura tributaria, contributiva e perequativa RS 349.210.537,00 RR 162.362.483,76 R -3.882.380,29 EP 182.965.672,95
CP 852.561.129,56 RC 653.841.773,48 A 851.106.416,52 CP -1.454.713,04 EC 197.264.643,04
CS 961.511.000,33 TR 816.204.257,24 CS -145.306.743,09 TR 380.230.315,99
TITOLO 2: Trasferimenti correnti RS 147.188.690,73 RR 61.417.606,74 R -7.130.206,96 EP 78.640.877,03
CP 320.367.900,46 RC 200.179.797,29 A 280.210.338,41 CP -40.157.562,05 EC 80.030.541,12
CS 465.797.988,81 TR 261.597.404,03 CS -204.200.584,78 TR 158.671.418,15
TOTALE GENERALE DELLE ENTRATE RS 0,00 RR 0,00 R 0,00 EP 0,00
CP 1.172.929.030,02 RC 854.021.570,77 A 1.131.316.754,93 CP -41.612.275,09 EC 277.295.184,16
CS 1.427.308.989,14 TR 1.077.801.661,27 CS -349.507.327,87 TR 538.901.734,14
"""


def test_spese_parser_extracts_missioni_and_measures():
    items = normalize_spese_missioni([(45, _SPESE_TEXT)])
    voci = {(i.code, i.measure): i.value for i in items if i.level == "voce"}
    # Missione 01: impegni and pagamenti totali on distinct rows.
    assert voci[("01", "impegni")] == Decimal("274018862.88")
    assert voci[("01", "pagamenti_totali")] == Decimal("276292612.21")
    assert voci[("01", "previsioni")] == Decimal("347001906.60")
    assert voci[("02", "impegni")] == Decimal("1731776.90")
    # The DISAVANZO preamble row must not become a voce.
    assert all(i.name != "" and not i.name.startswith("DISAVANZO") for i in items)
    # page attribution
    assert all(i.page == 45 for i in items)


def test_spese_parser_grand_total():
    items = normalize_spese_missioni([(45, _SPESE_TEXT)])
    tot = {i.measure: i.value for i in items if i.level == "totale"}
    assert tot["impegni"] == Decimal("275750639.78")
    assert tot["pagamenti_totali"] == Decimal("278030865.90")


def test_entrate_parser_keeps_first_occurrence_of_recurring_labels():
    items = normalize_entrate([(10, _ENTRATE_TEXT)])
    voci = {(i.code, i.measure): i.value for i in items if i.level == "voce"}
    # CP recurs (previsioni then maggiori/minori): keep previsioni.
    assert voci[("1", "previsioni")] == Decimal("852561129.56")
    # TR recurs (riscossioni then residui): keep riscossioni (cassa in).
    assert voci[("1", "riscossioni_totali")] == Decimal("816204257.24")
    assert voci[("1", "accertamenti")] == Decimal("851106416.52")
    # The FONDO PLURIENNALE preamble row must not become a titolo.
    assert all(not i.name.startswith("FONDO") for i in items)


def test_rendiconto_validator_passes_when_voci_sum_to_total():
    items = normalize_spese_missioni([(45, _SPESE_TEXT)]) + normalize_entrate([(10, _ENTRATE_TEXT)])
    assert validate_rendiconto_totals(items)[0].passed


def test_rendiconto_validator_fails_on_broken_total():
    items = [
        RendicontoItem("spesa", "voce", "01", "A", "impegni", Decimal("100"), 1),
        RendicontoItem("spesa", "voce", "02", "B", "impegni", Decimal("100"), 1),
        RendicontoItem("spesa", "totale", None, "Totale", "impegni", Decimal("999"), 1),
        RendicontoItem("spesa", "voce", "01", "A", "pagamenti_totali", Decimal("50"), 1),
        RendicontoItem("spesa", "totale", None, "Totale", "pagamenti_totali", Decimal("50"), 1),
    ]
    assert not validate_rendiconto_totals(items)[0].passed


@pytest.mark.skipif(not DB_PATH.exists(), reason="database not built")
def test_confronto_comuni_includes_torino_matching_rendiconto():
    """The cross-city comparison table carries at least Torino, and Torino's totals
    there equal the authoritative ``rendiconto`` totals (same BDAP source)."""
    from src.database.queries import Repository

    repo = Repository()
    try:
        cities = {c["comune"] for c in repo.confronto_cities()}
        if not cities:
            pytest.skip("no comparison data loaded")
        assert "TORINO" in cities
        for kind, measure in (("spesa", "pagamenti_totali"), ("entrata", "riscossioni_totali")):
            conf = {int(r["year"]): float(r["value"])
                    for r in repo.confronto_totals(kind=kind, measure=measure)
                    if r["comune"] == "TORINO"}
            for year, val in conf.items():
                tot = repo.rendiconto_total(kind=kind, measure=measure, year=year)
                assert tot is not None and abs(float(tot["value"]) - val) < 0.01, (
                    f"{year} {kind} {measure}: comparison {val} != rendiconto {tot}")
    finally:
        repo.close()


@pytest.mark.skipif(not DB_PATH.exists(), reason="database not built")
def test_rendiconto_ingested_and_reconciles():
    from src.database.queries import Repository

    repo = Repository()
    try:
        years = repo.rendiconto_years()
        assert {2021, 2022, 2023, 2024, 2025} <= set(years)
        for year in years:
            miss = repo.rendiconto(kind="spesa", measure="impegni", year=year)
            # the riepilogo lists the non-zero missioni; the exact count varies by
            # year (e.g. 2019, sourced from CSV, omits one more zero missione).
            assert 18 <= len(miss) <= 23, f"{year}: unexpected missioni count {len(miss)}"
            tot = repo.rendiconto_total(kind="spesa", measure="impegni", year=year)
            assert tot is not None
            s = sum(float(m["value"]) for m in miss)
            assert abs(s - float(tot["value"])) < 1.0, f"{year}: missioni do not sum to total"
    finally:
        repo.close()
