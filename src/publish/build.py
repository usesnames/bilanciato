"""Publish the structured data as a static, LLM-readable site.

Motivation: the Streamlit dashboard is a live websocket app, so an LLM that is
merely told to "go read the bilanciaTo data site" cannot consume it. This builder
emits a fully static ``site/`` directory that any agent (or human) can fetch:

    site/
      llms.txt                  index for LLMs (the emerging llms.txt convention)
      index.html                overview, key figures + provenance in the HTML
      anno-<year>.html          per-year statements (real numbers, source pages)
      partecipate.html          consolidation-area entities
      data/*.json, data/*.csv   complete datasets (metrics, entities, notes, timeseries)

Every figure on every page and in every file carries its source document and PDF
page, so an answer grounded on this site stays verifiable (CLAUDE.md
"Explainability" / "Grounded Responses"). The site is host-anywhere static output
(GitHub Pages, Netlify, S3, or ``python -m http.server``); no API, no keys.

Run:
    python -m src.publish.build            # -> site/
    python -m src.publish.build <out_dir>  # custom output directory
"""

from __future__ import annotations

import csv
import html
import io
import json
import sys
from pathlib import Path
from typing import Any

from src.database.queries import Repository
from src.utils.config import SITE

# Consolidated statement categories shown on the per-year HTML pages, in order.
STATEMENT_ORDER = [
    ("balance_sheet_assets", "Stato Patrimoniale - Attivo"),
    ("balance_sheet_liabilities", "Stato Patrimoniale - Passivo"),
    ("income_statement", "Conto Economico"),
]
# Headline lines tracked across years (category, exact label, human label).
HEADLINES = [
    ("balance_sheet_assets", "TOTALE DELL'ATTIVO", "Totale Attivo"),
    ("balance_sheet_liabilities", "TOTALE DEL PASSIVO", "Totale Passivo"),
]


def _fmt(value: Any) -> str:
    """Plain, unambiguous numeric text for machine + human reading."""
    if value is None:
        return ""
    return f"{float(value):.2f}"


def _fmt_human(value: Any) -> str:
    if value is None:
        return "n/d"
    v = float(value)
    if abs(v) >= 1e9:
        return f"~{v / 1e9:.2f} miliardi EUR"
    if abs(v) >= 1e6:
        return f"~{v / 1e6:.1f} milioni EUR"
    return f"{v:.2f} EUR"


# -- data file writers --------------------------------------------------------
def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


# -- HTML helpers -------------------------------------------------------------
PAGE_CSS = """
:root { color-scheme: light dark; }
body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
       max-width: 1000px; margin: 0 auto; padding: 1.5rem; line-height: 1.5; }
h1 { margin-bottom: .2rem; } .sub { color: #666; margin-top: 0; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .92rem; }
th, td { border: 1px solid #ccc; padding: .35rem .5rem; text-align: left; vertical-align: top; }
th { background: #f3f3f3; } td.num { text-align: right; font-variant-numeric: tabular-nums; }
nav a { margin-right: 1rem; } .prov { color: #777; font-size: .85rem; }
.card { border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin: .6rem 0; }
"""


def _doc(title: str, body: str) -> str:
    return (
        "<!doctype html>\n<html lang=\"it\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n<style>{PAGE_CSS}</style>\n</head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def _nav() -> str:
    return (
        '<nav><a href="index.html">Panoramica</a>'
        '<a href="partecipate.html">Partecipate</a>'
        '<a href="llms.txt">llms.txt</a>'
        '<a href="data/">Dati (JSON/CSV)</a></nav>'
    )


def _esc(text: Any) -> str:
    # Element text: escape only &,<,> (not quotes) so apostrophes in labels like
    # "TOTALE DELL'ATTIVO" stay literal and readable for an LLM fetching the HTML.
    return html.escape("" if text is None else str(text), quote=False)


def _table(headers: list[str], rows: list[list[Any]], num_cols: set[int] | None = None) -> str:
    num_cols = num_cols or set()
    out = ["<table>", "<thead><tr>"]
    out += [f"<th>{_esc(h)}</th>" for h in headers]
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for i, cell in enumerate(row):
            cls = ' class="num"' if i in num_cols else ""
            out.append(f"<td{cls}>{_esc(cell)}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


# -- builders -----------------------------------------------------------------
def build_data_files(repo: Repository, data_dir: Path) -> dict[str, int]:
    data_dir.mkdir(parents=True, exist_ok=True)
    docs = repo.documents()
    metrics = repo.all_metrics()
    entities = repo.all_entities()
    entity_metrics = repo.all_entity_metrics()
    notes = repo.all_note_items()
    rendiconto = repo.all_rendiconto()
    debito = repo.all_debito()
    capitoli = repo.all_capitoli()  # analytic per-capitolo detail (large: CSV only)

    # Multi-year series for the headline totals (one authoritative value per year).
    timeseries = {}
    for category, label, _human in HEADLINES:
        pts = repo.metric_timeseries(label, category=category)
        if pts:
            timeseries[label] = pts

    _write_json(data_dir / "documents.json", docs)
    _write_json(data_dir / "metrics.json", metrics)
    _write_json(data_dir / "entities.json", entities)
    _write_json(data_dir / "entity_metrics.json", entity_metrics)
    _write_json(data_dir / "note_items.json", notes)
    _write_json(data_dir / "rendiconto.json", rendiconto)
    _write_json(data_dir / "debito.json", debito)
    _write_json(data_dir / "timeseries.json", timeseries)
    _write_csv(data_dir / "metrics.csv", metrics)
    _write_csv(data_dir / "entities.csv", entities)
    _write_csv(data_dir / "entity_metrics.csv", entity_metrics)
    _write_csv(data_dir / "note_items.csv", notes)
    _write_csv(data_dir / "rendiconto.csv", rendiconto)
    _write_csv(data_dir / "debito.csv", debito)
    # The analytic per-capitolo detail is large (tens of thousands of rows): CSV only.
    _write_csv(data_dir / "capitoli.csv", capitoli)

    # A small index so a fetch of data/ is self-describing.
    _write_json(data_dir / "index.json", {
        "documents": len(docs), "metrics": len(metrics), "entities": len(entities),
        "entity_metrics": len(entity_metrics), "note_items": len(notes),
        "rendiconto": len(rendiconto), "debito": len(debito), "capitoli": len(capitoli),
        "files": ["documents.json", "metrics.json", "entities.json",
                  "entity_metrics.json", "note_items.json", "rendiconto.json",
                  "debito.json", "timeseries.json", "metrics.csv", "entities.csv",
                  "entity_metrics.csv", "note_items.csv", "rendiconto.csv",
                  "debito.csv", "capitoli.csv"],
    })
    return {"documents": len(docs), "metrics": len(metrics), "entities": len(entities),
            "entity_metrics": len(entity_metrics), "note_items": len(notes),
            "rendiconto": len(rendiconto), "debito": len(debito),
            "capitoli": len(capitoli)}


def build_year_page(repo: Repository, out: Path, year: int, filename: str) -> None:
    """Per-year statements, taking the figures from that year's own document."""
    body = [f"<h1>Bilancio Consolidato {year}</h1>",
            f'<p class="sub">Comune di Torino - fonte: {_esc(filename)}. '
            "Tutti i valori in EUR. Ogni riga riporta la pagina del PDF di origine.</p>",
            _nav()]
    rows = [r for r in repo.metrics(year=year, limit=5000)
            if r["source_document"] == filename]
    for category, label in STATEMENT_ORDER:
        cat_rows = [r for r in rows if r["category"] == category]
        if not cat_rows:
            continue
        body.append(f"<h2>{_esc(label)}</h2>")
        table_rows = [[r["code"] or "", r["metric_name"], _fmt(r["value"]),
                       r["unit"], r["source_page"]] for r in cat_rows]
        body.append(_table(["Codice", "Voce", "Valore", "Unità", "Pag. PDF"],
                           table_rows, num_cols={2}))
    out.write_text(_doc(f"Bilancio Consolidato {year} - bilanciaTo", "\n".join(body)),
                   encoding="utf-8")


def build_entities_page(repo: Repository, out: Path) -> None:
    body = ["<h1>Partecipate / Area di consolidamento</h1>",
            '<p class="sub">Entità del Gruppo Amministrazione Pubblica del Comune di Torino. '
            "Quota di possesso e tipo per anno; pagina del PDF di origine indicata.</p>",
            _nav()]
    ents = repo.all_entities()
    table_rows = [[e["year"], e["canonical_name"], e["entity_type"] or "",
                   _fmt(e["ownership_percentage"]) if e["ownership_percentage"] is not None else "",
                   e["source_page"]] for e in ents]
    body.append(_table(["Anno", "Denominazione", "Tipo", "Quota %", "Pag. PDF"],
                       table_rows, num_cols={3}))
    out.write_text(_doc("Partecipate - bilanciaTo", "\n".join(body)), encoding="utf-8")


def build_index(repo: Repository, out: Path, doc_years: list[tuple[int, str]]) -> None:
    docs = repo.documents()
    body = ["<h1>bilanciaTo</h1>",
            '<p class="sub">Bilancio Consolidato del Comune di Torino - dati strutturati, '
            "estratti dai PDF ufficiali. Ogni valore è tracciabile alla pagina di origine.</p>",
            _nav(), "<h2>Indicatori chiave</h2>"]
    for category, label, human in HEADLINES:
        pts = repo.metric_timeseries(label, category=category)
        if not pts:
            continue
        body.append(f'<div class="card"><strong>{_esc(label)}</strong>')
        rows = [[p["year"], _fmt(p["value"]), _fmt_human(p["value"]),
                 p["source_document"], p["source_page"]] for p in pts]
        body.append(_table(["Anno", "Valore (EUR)", "Indicativo", "Documento", "Pag."],
                           rows, num_cols={1}))
        body.append("</div>")
    body.append("<h2>Bilanci per anno</h2><ul>")
    for year, _fn in doc_years:
        body.append(f'<li><a href="anno-{year}.html">Bilancio Consolidato {year}</a></li>')
    body.append("</ul>")
    body.append("<h2>Documenti di origine</h2>")
    body.append(_table(["Anno", "File", "Pagine"],
                       [[d["year"], d["filename"], d["page_count"]] for d in docs]))
    body.append('<p class="prov">Dati completi in formato JSON/CSV: '
                '<a href="data/">data/</a> · indice per LLM: <a href="llms.txt">llms.txt</a></p>')
    out.write_text(_doc("bilanciaTo - Bilancio Consolidato Comune di Torino", "\n".join(body)),
                   encoding="utf-8")


def build_llms_txt(repo: Repository, out: Path, doc_years: list[tuple[int, str]]) -> None:
    docs = repo.documents()
    yrs = repo.years()
    lines = [
        "# bilanciaTo - Bilancio Consolidato del Comune di Torino",
        "",
        "> Dati finanziari strutturati estratti dai PDF ufficiali del Bilancio "
        "Consolidato del Comune di Torino. Ogni valore è tracciabile al documento e "
        "alla pagina di origine. Valori in EUR salvo diversa indicazione (unit=PCT per "
        "le percentuali). Rispondi citando sempre anno, documento e pagina.",
        "",
        f"Anni disponibili: {', '.join(str(y) for y in yrs)}. "
        f"Documenti: {len(docs)}.",
        "",
        "## Indicatori chiave",
    ]
    for category, label, _human in HEADLINES:
        pts = repo.metric_timeseries(label, category=category)
        for p in pts:
            lines.append(
                f"- {label} {p['year']}: {_fmt(p['value'])} EUR "
                f"(fonte: {p['source_document']}, pag. {p['source_page']})"
            )
    lines += ["", "## Pagine (numeri reali nell'HTML)"]
    lines.append("- [Panoramica](index.html): indicatori chiave e indice")
    for year, _fn in doc_years:
        lines.append(f"- [Bilancio Consolidato {year}](anno-{year}.html): "
                     "stato patrimoniale (attivo/passivo) e conto economico")
    lines.append("- [Partecipate](partecipate.html): area di consolidamento")
    lines += ["", "## Dati completi (machine-readable)",
              "- [metrics.json](data/metrics.json): tutte le righe di bilancio "
              "(year, category, code, metric_name, value, unit, source_page, source_document)",
              "- [timeseries.json](data/timeseries.json): serie storiche degli aggregati",
              "- [entities.json](data/entities.json): entità consolidate per anno",
              "- [entity_metrics.json](data/entity_metrics.json): dati per entità "
              "(spesa personale, valutazione partecipazioni)",
              "- [note_items.json](data/note_items.json): tabelle di dettaglio della nota integrativa",
              "- [rendiconto.json](data/rendiconto.json): rendiconto della gestione del "
              "solo Comune (conto del bilancio): spese per missione ed entrate per titolo, "
              "con previsioni, impegni/accertamenti (competenza) e pagamenti/riscossioni "
              "(cassa). NB: base finanziaria e perimetro diversi dal bilancio consolidato.",
              "- [debito.json](data/debito.json): evoluzione dell'indebitamento del Comune "
              "2018-2025 (residuo debito, nuovi prestiti, rimborsi, debito a fine anno, "
              "oneri finanziari/interessi, abitanti, debito per abitante); fonte: Relazioni "
              "del Collegio dei revisori dei conti.",
              "- [capitoli.csv](data/capitoli.csv): rendiconto analitico per capitoli "
              "(Conto di Bilancio D.Lgs 118 analitico) -- ogni capitolo di spesa/entrata con "
              "missione/programma/macroaggregato (o titolo/tipologia/categoria), previsioni, "
              "competenza, cassa e residui. I capitoli sommano agli aggregati per missione/titolo.",
              "- versioni CSV degli stessi file in [data/](data/)",
              "",
              "## Note",
              "- Le categorie `aggregate_*` sono somme pre-consolidamento (provvisorie, "
              "prima delle elisioni infragruppo); per i dati consolidati usare le "
              "categorie senza prefisso.",
              "- Identità di bilancio: TOTALE DELL'ATTIVO = TOTALE DEL PASSIVO.",
              "- Fonte autorevole per un anno: il documento il cui anno coincide con l'anno del dato.",
              ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def publish(out_dir: Path = SITE) -> dict[str, Any]:
    repo = Repository()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        counts = build_data_files(repo, out_dir / "data")

        # Years that have their own *consolidato* document get a rendered statement
        # page. (Rendiconto documents share a year but have no `metrics` rows; their
        # data is published machine-readable under data/ instead.)
        docs = repo.documents()
        doc_years = sorted(
            ((d["year"], d["filename"]) for d in docs
             if d["document_type"] == "bilancio_consolidato"),
            reverse=True,
        )
        for year, filename in doc_years:
            build_year_page(repo, out_dir / f"anno-{year}.html", year, filename)
        build_entities_page(repo, out_dir / "partecipate.html")
        build_index(repo, out_dir / "index.html", doc_years)
        build_llms_txt(repo, out_dir / "llms.txt", doc_years)
    finally:
        repo.close()

    counts["years_pages"] = len(doc_years)
    counts["out_dir"] = str(out_dir)
    return counts


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else SITE
    result = publish(out_dir)
    print(f"published static site -> {result['out_dir']}")
    print(f"  {result['years_pages']} year pages; "
          f"{result['metrics']} metrics, {result['entities']} entities, "
          f"{result['entity_metrics']} entity-metrics, {result['note_items']} note-items")
    print("  files: index.html, anno-*.html, partecipate.html, llms.txt, data/*.json|csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
