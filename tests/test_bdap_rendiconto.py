"""Tests for the BDAP/RGS rendiconto open-data normalizer.

Small synthetic riepilogo fragments (the real per-region CSVs share these column
names) exercise: comune selection by name + soggetto type, US-decimal parsing,
titolo code normalization (01->1), zero-voce omission, and totals = sum of voci.
"""

from __future__ import annotations

from decimal import Decimal

from src.normalization import bdap_rendiconto as bdap

# Spese "Riepilogo Missioni": one comune we want (COMUNE DI TORINO / COMUNI), one
# decoy sharing the name as a province soggetto, and a zero-everything missione.
_SPESE = (
    "Descrizione Tipologia Soggetto;Descrizione Comune;Codice Missione;"
    "Descrizione Missione;Previsioni Definitive di Competenza;Impegni;Totale Pagamenti\n"
    "COMUNI;TORINO;01;Servizi istituzionali;100.50;90.25;80.00\n"
    "COMUNI;TORINO;12;Diritti sociali;50.00;40.00;30.00\n"
    "COMUNI;TORINO;13;Tutela della salute;0;0;0\n"
    "PROVINCE/CITTA' METROPOLITANE;TORINO;01;Servizi istituzionali;999.99;999.99;999.99\n"
    "COMUNI;MONCALIERI;01;Servizi istituzionali;7.00;7.00;7.00\n"
)

_ENTRATE = (
    "Descrizione Tipologia Soggetto;Descrizione Comune;Codice Titolo;"
    "Descrizione Titolo;Previsioni Definitive di Competenza;Accertamenti;Totale Riscossioni\n"
    "COMUNI;TORINO;01;Entrate tributarie;200.00;180.00;170.00\n"
    "COMUNI;TORINO;07;Anticipazioni;1000.00;500.00;500.00\n"
    "COMUNI;MONCALIERI;01;Entrate tributarie;9.00;9.00;9.00\n"
)


def test_comune_selection_excludes_other_soggetti_and_comuni():
    hdr, rows = bdap.load_riepilogo(_SPESE)
    sel = bdap.comune_rows(hdr, rows, "TORINO")
    # Only the three COMUNI/TORINO rows -- not the province decoy, not Moncalieri.
    assert len(sel) == 3
    assert all(r[hdr.index("Descrizione Tipologia Soggetto")] == "COMUNI" for r in sel)


def test_spese_voci_and_total():
    hdr, rows = bdap.load_riepilogo(_SPESE)
    sel = bdap.comune_rows(hdr, rows, "TORINO")
    items = bdap.normalize_spese(hdr, sel)
    voci = {(i.code, i.measure): i.value for i in items if i.level == "voce"}
    # US-decimal parsed; the all-zero missione 13 is omitted.
    assert voci[("01", "impegni")] == Decimal("90.25")
    assert voci[("01", "pagamenti_totali")] == Decimal("80.00")
    assert voci[("01", "previsioni")] == Decimal("100.50")
    assert ("13", "impegni") not in voci
    codes = {c for (c, _m) in voci}
    assert codes == {"01", "12"}
    tot = {i.measure: i.value for i in items if i.level == "totale"}
    assert tot["impegni"] == Decimal("130.25")  # 90.25 + 40.00
    assert tot["pagamenti_totali"] == Decimal("110.00")  # 80 + 30


def test_entrate_titolo_code_normalized_to_single_digit():
    hdr, rows = bdap.load_riepilogo(_ENTRATE)
    sel = bdap.comune_rows(hdr, rows, "TORINO")
    items = bdap.normalize_entrate(hdr, sel)
    voci = {(i.code, i.measure): i.value for i in items if i.level == "voce"}
    # BDAP prints "01"/"07"; we normalize to "1"/"7" to match the PDF parser.
    assert voci[("1", "accertamenti")] == Decimal("180.00")
    assert voci[("7", "riscossioni_totali")] == Decimal("500.00")
    tot = {i.measure: i.value for i in items if i.level == "totale"}
    assert tot["accertamenti"] == Decimal("680.00")  # 180 + 500


def test_names_borrowed_when_provided():
    hdr, rows = bdap.load_riepilogo(_SPESE)
    sel = bdap.comune_rows(hdr, rows, "TORINO")
    items = bdap.normalize_spese(hdr, sel, names={"01": "Servizi istituzionali, generali e di gestione"})
    name01 = next(i.name for i in items if i.code == "01" and i.level == "voce")
    assert name01 == "Servizi istituzionali, generali e di gestione"
    # A code not in the map falls back to the BDAP descrizione.
    name12 = next(i.name for i in items if i.code == "12" and i.level == "voce")
    assert name12 == "Diritti sociali"
