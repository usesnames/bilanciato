"""Tests for the "Formato aperto" CSV rendiconto normalizer (used for 2019).

Pure-function tests over tiny in-memory CSVs: entrate tipologie aggregate to
per-titolo voci (and the grand total is the titoli sum, excluding FPV/avanzo);
spese per-missione totals are read from the TOTALE MISSIONI row; zero voci are
omitted; and the voci reconcile to the grand totals.
"""

from __future__ import annotations

from decimal import Decimal

from src.etl import validate
from src.normalization.rendiconto_csv import normalize_entrate_csv, normalize_spese_csv

_ENTRATE_CSV = """Titolo;Tipologia;Accertamenti;Riscossioni
Fondo pluriennale vincolato per spese correnti;;76.463.590,89;0,00
Utilizzo Risultato di amministrazione;;11.148.285,01;0,00
1-Entrate correnti;TIPOLOGIA 101 - Imposte;600.000,00;500.000,00
1-Entrate correnti;TIPOLOGIA 301 - Fondi perequativi;400.000,00;400.000,00
TOTALE TITOLO I;;1.000.000,00;900.000,00
2-Trasferimenti correnti;TIPOLOGIA 101 - Trasferimenti;250.000,00;200.000,00
TOTALE TITOLO II;;250.000,00;200.000,00
8-Premi di emissione;TIPOLOGIA 100 - Premi;0,00;0,00
TOTALE TITOLI;;1.250.000,00;1.100.000,00
TOTALE GENERALE DELLE ENTRATE;;1.337.611.875,90;1.100.000,00
"""

# Two missioni (codes 01 and 10) with values, the rest zero. The header just needs
# the right number of columns; only the TOTALE MISSIONI row is read.
_N_MISS = 23
_SPESE_HEADER = "Titolo;Macroaggregato;" + ";".join(f"c{i}" for i in range(_N_MISS * 3 + 4))
def _spese_csv() -> str:
    # per-missione triplets (Impegnato;FPV;Pagato); missione 01 at index 0, 10 at index 9
    cells = ["0,00"] * (_N_MISS * 3)
    cells[0 * 3 + 0] = "300.000,00"   # missione 01 impegnato
    cells[0 * 3 + 2] = "290.000,00"   # missione 01 pagato
    cells[9 * 3 + 0] = "88.000,00"    # missione 10 impegnato
    cells[9 * 3 + 2] = "124.000,00"   # missione 10 pagato
    # trailing: Ripiano disavanzo, then Totale generale Impegnato/FPV/Pagato
    tail = ["0,00", "388.000,00", "0,00", "414.000,00"]
    row = "TOTALE MISSIONI - TOTALE GENERALE DELLE SPESE;;" + ";".join(cells + tail)
    return _SPESE_HEADER + "\n" + row + "\n"


def test_entrate_aggregates_to_titoli(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text(_ENTRATE_CSV, encoding="latin-1")
    items = normalize_entrate_csv(p)
    voci = {it.code: it for it in items if it.level == "voce" and it.measure == "accertamenti"}
    # titolo 1 = sum of its tipologie; titolo 8 (all zero) omitted
    assert voci["1"].value == Decimal("1000000.00")
    assert "8" not in voci
    assert "Entrate correnti" in voci["1"].name  # "N-" prefix stripped
    # grand total = sum of titoli (NOT the CSV's TOTALE GENERALE incl. FPV/avanzo)
    tot = next(it for it in items if it.level == "totale" and it.measure == "accertamenti")
    assert tot.value == Decimal("1250000.00")


def test_spese_reads_per_missione_totals(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text(_spese_csv(), encoding="latin-1")
    names = {"01": "Servizi istituzionali", "10": "Trasporti e diritto alla mobilità"}
    items = normalize_spese_csv(p, missione_names=names)
    imp = {it.code: it.value for it in items if it.level == "voce" and it.measure == "impegni"}
    assert imp == {"01": Decimal("300000.00"), "10": Decimal("88000.00")}  # zero missioni omitted
    tot = next(it for it in items if it.level == "totale" and it.measure == "impegni")
    assert tot.value == Decimal("388000.00")


def test_csv_items_reconcile(tmp_path):
    pe, ps = tmp_path / "e.csv", tmp_path / "s.csv"
    pe.write_text(_ENTRATE_CSV, encoding="latin-1")
    ps.write_text(_spese_csv(), encoding="latin-1")
    items = normalize_entrate_csv(pe) + normalize_spese_csv(ps, missione_names={})
    checks = validate.validate_rendiconto_totals(items)
    assert all(c.passed for c in checks)
