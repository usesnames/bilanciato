"""Tests for the curated municipal-debt series.

Pure-function tests over the curated dataset and its consistency validator, plus
a DB regression that the series is loaded and the per-capita figure reconciles.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.etl.validate import validate_debito
from src.normalization.debito import DEBITO_MEASURES, debito_items
from src.utils.config import DB_PATH


def test_series_spans_2018_2025():
    years = sorted({it.year for it in debito_items()})
    assert years == [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]


def test_every_item_has_known_measure_and_unit():
    for it in debito_items():
        assert it.measure in DEBITO_MEASURES
        assert it.unit == DEBITO_MEASURES[it.measure][1]
        assert it.source  # provenance is never empty


def test_validator_passes_on_curated_data():
    checks = validate_debito(debito_items())
    assert checks and all(c.passed for c in checks), [
        (c.name, c.detail) for c in checks if not c.passed
    ]


def test_chain_fine_anno_equals_next_residuo():
    by = {(it.year, it.measure): it.value for it in debito_items()}
    for y in range(2018, 2025):
        assert by[(y, "debito_fine_anno")] == by[(y + 1, "residuo_iniziale")]


def test_pro_capite_matches_debt_over_residents():
    by = {(it.year, it.measure): it.value for it in debito_items()}
    for y in (2018, 2024, 2025):
        expected = by[(y, "debito_fine_anno")] / by[(y, "abitanti")]
        assert abs(expected - by[(y, "debito_pro_capite")]) <= Decimal("0.5")


def test_validator_fails_on_broken_chain():
    items = debito_items()
    # Corrupt one fine-anno so it no longer matches the next year's opening.
    bad = [
        it if not (it.year == 2020 and it.measure == "debito_fine_anno")
        else type(it)(it.year, it.measure, it.value + Decimal("1000000"), it.unit, it.source)
        for it in items
    ]
    checks = validate_debito(bad)
    assert any(c.name == "debito_chain" and not c.passed for c in checks)


@pytest.mark.skipif(not DB_PATH.exists(), reason="database not built")
def test_debito_loaded_and_reconciles():
    from src.database.queries import Repository

    repo = Repository()
    try:
        years = repo.debito_years()
        assert {2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025} <= set(years)
        fine = {int(r["year"]): r["value"] for r in repo.debito(measure="debito_fine_anno")}
        opening = {int(r["year"]): r["value"] for r in repo.debito(measure="residuo_iniziale")}
        for y in range(2018, 2025):
            assert float(fine[y]) == pytest.approx(float(opening[y + 1]), abs=0.01)
    finally:
        repo.close()
