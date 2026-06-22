"""Query-layer tests.

Run against the real ingested DuckDB (the project's source of truth) and self-skip
if it has not been built yet.
"""

from __future__ import annotations

import pytest

from src.utils.config import DB_PATH

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(), reason="database not built; run `python -m src.etl.ingest`"
)


@pytest.fixture(scope="module")
def repo():
    from src.database.queries import Repository

    r = Repository()
    yield r
    r.close()


def test_documents_and_years(repo):
    docs = repo.documents()
    assert docs
    assert {"id", "filename", "year", "checksum", "page_count"} <= set(docs[0])
    assert set(repo.years()) >= {2021, 2022, 2023, 2024}


def test_entity_metric_timeseries_spans_years(repo):
    """spesa_personale is a multi-year per-entity metric (the dashboard's example)."""
    assert "spesa_personale" in repo.entity_metrics_multiyear("iren")
    pts = repo.entity_metric_timeseries("iren", "spesa_personale")
    years = [p["year"] for p in pts]
    assert len(years) == len(set(years))  # one value per year
    assert {2021, 2022, 2023, 2024} <= set(years)
    for p in pts:
        assert p["value"] is not None and p["source_page"] >= 1
    assert {e["canonical_slug"] for e in repo.entities_with_metric("spesa_personale")} >= {"iren", "amiat"}


def test_metrics_carry_provenance(repo):
    rows = repo.metrics(year=2024, limit=5)
    assert rows
    for r in rows:
        assert r["year"] == 2024
        assert r["source_document"]
        assert r["source_page"] >= 1


def test_balance_sheet_identity(repo):
    assets = repo.metrics(year=2024, category="balance_sheet_assets", query="totale dell'attivo")
    liabs = repo.metrics(year=2024, category="balance_sheet_liabilities", query="totale del")
    a = next(r["value"] for r in assets if r["metric_name"].lower().startswith("totale dell'attivo"))
    p = next(
        r["value"] for r in liabs
        if r["metric_name"].lower().startswith("totale del") and "attivo" not in r["metric_name"].lower()
    )
    assert a == p == pytest.approx(15250041769.33, abs=0.01)


def test_timeseries_one_value_per_year(repo):
    pts = repo.metric_timeseries("TOTALE DELL'ATTIVO", category="balance_sheet_assets")
    years = [p["year"] for p in pts]
    assert len(years) == len(set(years))
    assert min(years) <= 2022 and max(years) >= 2024
    by_year = {p["year"]: p["value"] for p in pts}
    assert by_year[2024] == pytest.approx(15250041769.33, abs=0.01)


def test_search_finds_equity_valued_entity(repo):
    """SMAT lives only in entity_metrics (valued at equity) yet search must find it."""
    res = repo.search("smat")
    assert "smat" in {e["canonical_slug"] for e in res["entities"]}


def test_full_exports_nonempty(repo):
    assert len(repo.all_metrics()) > 1000
    assert repo.all_entities()
    assert repo.all_entity_metrics()
    assert repo.all_note_items()
