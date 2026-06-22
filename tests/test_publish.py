"""Static-publisher tests: the site builds with correct figures and intact
provenance in both the HTML and the JSON exports.
"""

from __future__ import annotations

import json

import pytest

from src.utils.config import DB_PATH

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(), reason="database not built; run `python -m src.etl.ingest`"
)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    from src.publish.build import publish

    out = tmp_path_factory.mktemp("site")
    publish(out)
    return out


def test_core_files_exist(site):
    for rel in ["index.html", "llms.txt", "partecipate.html",
                "data/metrics.json", "data/timeseries.json", "data/metrics.csv"]:
        assert (site / rel).exists(), rel
    # one HTML page per source-document year
    assert list(site.glob("anno-*.html"))


def test_metrics_json_has_provenance(site):
    rows = json.loads((site / "data" / "metrics.json").read_text())
    assert len(rows) > 1000
    r = rows[0]
    assert {"year", "category", "metric_name", "value", "unit",
            "source_page", "source_document"} <= set(r)


def test_headline_value_in_llms_txt_and_html(site):
    # The exact consolidated total must appear verbatim in the LLM index ...
    llms = (site / "llms.txt").read_text()
    assert "15250041769.33" in llms
    assert "pag. 15" in llms
    # ... and in the rendered 2024 statement HTML, with its source page.
    html_2024 = (site / "anno-2024.html").read_text()
    assert "15250041769.33" in html_2024
    assert "DELL'ATTIVO" in html_2024  # apostrophe left literal for LLM reading


def test_timeseries_json_shape(site):
    ts = json.loads((site / "data" / "timeseries.json").read_text())
    assert "TOTALE DELL'ATTIVO" in ts
    series = {p["year"]: p["value"] for p in ts["TOTALE DELL'ATTIVO"]}
    assert series[2024] == pytest.approx(15250041769.33, abs=0.01)
    assert min(series) <= 2022
