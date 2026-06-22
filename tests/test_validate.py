"""Validation-layer unit tests.

These are pure-function tests over hand-built NormalizedRow lists (no DB), plus a
regression guard that the opening line items of the income statement are present
in the ingested database -- the failure mode of a wrong page range that dropped
the first voci (codes 1..n on the "SCHEMA ..." page).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.etl.validate import validate_gestione_totals, validate_statement_subtotals
from src.normalization.statements import NormalizedRow
from src.utils.config import DB_PATH


def _row(code, desc, value):
    return NormalizedRow("income_statement", 1, code, desc, value, None, value is not None)


def test_subtotals_pass_when_letters_sum_to_parent():
    rows = [
        _row("3", "Proventi da trasferimenti e contributi", Decimal("100")),
        _row("a", "Proventi da trasferimenti correnti", Decimal("60")),
        _row("b", "Quota annuale di contributi", Decimal("30")),
        _row("c", "Contributi agli investimenti", Decimal("10")),
    ]
    assert validate_statement_subtotals(rows)[0].passed


def test_subtotals_fail_when_a_sub_voce_is_missing():
    rows = [
        _row("3", "Proventi da trasferimenti e contributi", Decimal("100")),
        _row("a", "Proventi da trasferimenti correnti", Decimal("60")),
        _row("b", "Quota annuale di contributi", Decimal("30")),  # missing c=10
    ]
    assert not validate_statement_subtotals(rows)[0].passed


def test_subtotals_skip_header_row_between_sub_voci():
    """A repeated column header at a page break must not split a sub-voce group."""
    rows = [
        _row("3", "Proventi da trasferimenti e contributi", Decimal("100")),
        _row("a", "Proventi da trasferimenti correnti", Decimal("60")),
        _row("", "CONTO ECONOMICO", None),  # page-break header, no value
        _row("b", "Quota annuale di contributi", Decimal("40")),
    ]
    assert validate_statement_subtotals(rows)[0].passed


def test_subtotals_ignore_di_cui_rows():
    """'di cui' is an of-which highlight, not an additive component."""
    rows = [
        _row("1.1", "Terreni", Decimal("500")),
        _row("a", "di cui in leasing finanziario", Decimal("3")),
    ]
    # No additive children -> nothing checked, so it passes.
    assert validate_statement_subtotals(rows)[0].passed


def test_gestione_totals_reconcile_section_a():
    rows = [
        _row("A", "COMPONENTI POSITIVI DELLA GESTIONE", None),
        _row("1", "Proventi da tributi", Decimal("70")),
        _row("2", "Proventi da fondi perequativi", Decimal("30")),
        _row("", "totale componenti positivi della gestione A)", Decimal("100")),
    ]
    assert validate_gestione_totals(rows)[0].passed


def test_gestione_totals_fail_on_wrong_total():
    rows = [
        _row("A", "COMPONENTI POSITIVI DELLA GESTIONE", None),
        _row("1", "Proventi da tributi", Decimal("70")),
        _row("2", "Proventi da fondi perequativi", Decimal("30")),
        _row("", "totale componenti positivi della gestione A)", Decimal("999")),
    ]
    assert not validate_gestione_totals(rows)[0].passed


@pytest.mark.skipif(not DB_PATH.exists(), reason="database not built")
def test_income_statement_opening_voci_present():
    """Regression: the first numbered voci (on the SCHEMA page) must be ingested."""
    from src.database.queries import Repository

    repo = Repository()
    try:
        for year in (2021, 2022, 2023, 2024):
            rows = repo.metrics(year=year, category="income_statement", limit=2000)
            codes = {r["code"] for r in rows}
            assert {"1", "2", "3"} <= codes, f"{year} missing opening voci: have {sorted(codes)[:5]}"
            names = " ".join(r["metric_name"].lower() for r in rows)
            assert "proventi da tributi" in names, year
    finally:
        repo.close()
