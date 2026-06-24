"""Tests for the partecipate civil-code statements (SP + CE).

Pure-function tests over the number/column parser, plus a DB regression that the
loaded statements reconcile (TOTALE ATTIVO == TOTALE PASSIVO E NETTO, and the CE
result equals patrimonio netto's utile d'esercizio).
"""

from __future__ import annotations

import pytest

from src.normalization.entity_statements import _code_of, _parse_amount, _related_party
from src.utils.config import DB_PATH


def test_parse_amount_italian_and_negatives():
    assert _parse_amount("1.515.214.893") == 1515214893
    assert _parse_amount("(231.334)") == -231334
    assert _parse_amount("0") == 0
    assert _parse_amount("mesi") is None


def test_parse_amount_recovers_merged_leader():
    # dotted leaders fuse into the figure: "…SUBORDINAT_O____21_6_._1_72"
    assert _parse_amount("SUBORDINAT_O__________21_6_._1_72") == 216172


def test_code_detection():
    assert _code_of("A) CREDITI VERSO SOCI") == "A)"
    assert _code_of("B.III. IMMOBILIZZAZIONI FINANZIARIE") == "B.III."
    assert _code_of("D. RATEI E RISCONTI") == "D."
    assert _code_of("11 bis) Debiti vs imprese") == "11 bis)"
    assert _code_of("20 Imposte sul reddito") == "20"
    assert _code_of("d-bis) altre imprese") == "d-bis)"
    assert _code_of("Ratei e risconti attivi") == ""


def test_related_party_tagging():
    assert _related_party("4) Verso controllanti") == "socio"
    assert _related_party("5) Verso imprese sottoposte al controllo delle controllanti") == "gruppo_socio"
    assert _related_party("2) Verso imprese controllate") == "controllate"
    assert _related_party("1) Depositi bancari e postali") is None


@pytest.mark.skipif(not DB_PATH.exists(), reason="database not built")
def test_infra_statements_reconcile():
    from src.database.queries import Repository

    repo = Repository()
    try:
        years = repo.entity_statement_years("infratrasporti_to")
        assert {2024, 2023} <= set(years)
        rows = repo.entity_statements("infratrasporti_to", years=[2024, 2023])

        def find(category, year, pred):
            return next((r["value"] for r in rows
                         if r["category"] == category and int(r["year"]) == year
                         and pred(r["name"].replace(" ", "").upper())), None)

        for y in (2024, 2023):
            ta = find("stato_patrimoniale_attivo", y, lambda n: n == "TOTALEATTIVO")
            tp = find("stato_patrimoniale_passivo", y, lambda n: n.startswith("TOTALEPASSIVOENET"))
            assert ta is not None and tp is not None
            assert ta == tp, f"{y}: attivo {ta} != passivo {tp}"
            ce = find("conto_economico", y,
                      lambda n: n.startswith("21)UTILE") or "UTILE(PERDITA)DELL'ESER" in n)
            sp = find("stato_patrimoniale_passivo", y, lambda n: "UTILE(PERDITA)D'ESERCIZIO" in n)
            assert ce == sp, f"{y}: utile CE {ce} != utile SP {sp}"
    finally:
        repo.close()


@pytest.mark.skipif(not DB_PATH.exists(), reason="database not built")
def test_infra_in_entity_directory():
    from src.database.queries import Repository

    repo = Repository()
    try:
        slugs = {e["canonical_slug"] for e in repo.entity_directory()}
        assert "infratrasporti_to" in slugs
        assert "fct_holding" in slugs  # holding controlling GTT now surfaced too
    finally:
        repo.close()
