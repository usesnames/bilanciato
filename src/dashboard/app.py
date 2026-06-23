"""Streamlit dashboard for bilanciaTo (human-facing, interactive).

Reads the DuckDB database directly through ``src.database.queries`` (no HTTP API).
Designed for citizens, journalists and researchers: every figure shown carries its
source document and PDF page, so any number can be traced back to the official
report (CLAUDE.md "Explainability" / "Source Explorer").

For LLM/agent access there is a separate, statically published data site (see
``src/publish`` and the "Dati aperti / per LLM" page) that an LLM can fetch directly.

Run:
    streamlit run src/dashboard/app.py        # dashboard on :8501
"""

from __future__ import annotations

import re
import textwrap

import pandas as pd
import plotly.colors as pcolors
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.dashboard import glossary
from src.database.queries import Repository
from src.normalization.debito import DEBITO_MEASURES

st.set_page_config(page_title="bilanciaTo", page_icon="📊", layout="wide")

CATEGORY_LABELS = {
    "income_statement": "Conto economico (consolidato)",
    "balance_sheet_assets": "Stato patrimoniale - Attivo (consolidato)",
    "balance_sheet_liabilities": "Stato patrimoniale - Passivo (consolidato)",
    "aggregate_income_statement": "Conto economico (aggregato provvisorio)",
    "aggregate_balance_sheet_assets": "Stato patrimoniale - Attivo (aggregato)",
    "aggregate_balance_sheet_liabilities": "Stato patrimoniale - Passivo (aggregato)",
}

CATEGORY_DESCRIPTIONS = {
    "income_statement": (
        "**Conto economico consolidato** — fotografa ricavi e costi dell'intero "
        "Gruppo del Comune di Torino (capogruppo + circa 38 partecipate come Iren, "
        "GTT, SMAT) in un unico prospetto, secondo il principio della **competenza "
        "economica** (i valori sono registrati quando maturano, non quando il denaro "
        "si sposta). Non è il rendiconto della gestione: quello riguarda il solo Comune, "
        "su base di cassa, ed è un documento separato."
    ),
    "aggregate_income_statement": (
        "**Conto economico aggregato provvisorio** — somma aritmetica dei conti "
        "economici del Comune e di tutte le partecipate, prima di eliminare le "
        "operazioni interne al gruppo (es. fatture tra Comune e GTT). È il punto "
        "di partenza del consolidamento; i totali sono più alti di quelli consolidati "
        "proprio perché i flussi intragruppo non sono ancora stati cancellati."
    ),
    "balance_sheet_assets": (
        "**Stato patrimoniale consolidato — Attivo** — elenca tutto ciò che il Gruppo "
        "possiede o controlla alla data di chiusura dell'esercizio: immobili, "
        "infrastrutture, crediti, liquidità. I valori sono al netto degli ammortamenti "
        "e delle svalutazioni, e le partecipazioni interne al gruppo sono eliminate."
    ),
    "balance_sheet_liabilities": (
        "**Stato patrimoniale consolidato — Passivo** — mostra le fonti di "
        "finanziamento del Gruppo: debiti verso banche e fornitori, fondi rischi, "
        "trattamento di fine rapporto e patrimonio netto (differenza tra attivo e "
        "debiti). Deve pareggiare esattamente l'Attivo."
    ),
    "aggregate_balance_sheet_assets": (
        "**Stato patrimoniale aggregato provvisorio — Attivo** — somma degli attivi "
        "del Comune e delle partecipate prima delle rettifiche di consolidamento "
        "(partecipazioni e crediti/debiti reciproci non ancora eliminati)."
    ),
    "aggregate_balance_sheet_liabilities": (
        "**Stato patrimoniale aggregato provvisorio — Passivo** — somma dei passivi "
        "e patrimoni netti del Comune e delle partecipate, prima delle rettifiche "
        "di consolidamento."
    ),
}

# Human labels for the long-format per-entity metric names.
ENTITY_METRIC_LABELS = {
    "spesa_personale": "Spesa per il personale",
    "perc_consolidamento": "Percentuale di consolidamento",
    "incidenza_ricavi_comune": "Incidenza ricavi imputabili al Comune",
    "perdite_ripianate_comune": "Perdite ripianate dal Comune (ultimi 3 anni)",
    "quota_posseduta": "Quota posseduta",
    "valore_iscrizione_partecipazione": "Valore di iscrizione della partecipazione",
    "patrimonio_netto": "Patrimonio netto dell'organismo",
    "frazione_patrimonio_netto": "Frazione del patrimonio netto",
    "differenza_elisione": "Differenza di elisione",
}


def metric_label(name: str) -> str:
    return ENTITY_METRIC_LABELS.get(name, name.replace("_", " ").capitalize())


# -- data access (cached) -----------------------------------------------------
@st.cache_resource
def get_repo() -> Repository:
    try:
        return Repository()
    except FileNotFoundError as exc:
        st.error(f"{exc}")
        st.stop()


@st.cache_data(ttl=300)
def documents():
    return get_repo().documents()


@st.cache_data(ttl=300)
def years():
    return get_repo().years()


@st.cache_data(ttl=300)
def categories():
    return get_repo().metric_categories()


@st.cache_data(ttl=300)
def metrics(**kwargs):
    return get_repo().metrics(**kwargs)


@st.cache_data(ttl=300)
def timeseries(metric_name: str, category: str | None = None):
    return get_repo().metric_timeseries(metric_name, category=category)


@st.cache_data(ttl=300)
def entity_directory():
    return get_repo().entity_directory()


@st.cache_data(ttl=300)
def entities(**kwargs):
    return get_repo().entities(**kwargs)


@st.cache_data(ttl=300)
def entity_metrics(slug: str, year: int | None = None):
    return get_repo().entity_metrics(slug, year=year)


@st.cache_data(ttl=300)
def entity_metric_timeseries(slug: str, metric_name: str):
    return get_repo().entity_metric_timeseries(slug, metric_name)


@st.cache_data(ttl=300)
def entity_metrics_multiyear(slug: str):
    return get_repo().entity_metrics_multiyear(slug)


@st.cache_data(ttl=300)
def entities_with_metric(metric_name: str):
    return get_repo().entities_with_metric(metric_name)


@st.cache_data(ttl=300)
def rendiconto_years():
    return get_repo().rendiconto_years()


@st.cache_data(ttl=300)
def rendiconto(*, kind: str, measure: str, year: int | None = None, level: str = "voce"):
    return get_repo().rendiconto(kind=kind, measure=measure, year=year, level=level)


@st.cache_data(ttl=300)
def rendiconto_total(*, kind: str, measure: str, year: int):
    return get_repo().rendiconto_total(kind=kind, measure=measure, year=year)


@st.cache_data(ttl=300)
def capitoli_years():
    return get_repo().capitoli_years()


@st.cache_data(ttl=300)
def capitoli_tree(*, kind: str, year: int, measure: str):
    return get_repo().capitoli_tree(kind=kind, year=year, measure=measure)


@st.cache_data(ttl=300)
def capitoli_liv1(*, kind: str, year: int):
    return get_repo().capitoli_liv1(kind=kind, year=year)


@st.cache_data(ttl=300)
def capitoli(*, kind: str, year: int, measure: str, liv1=None, liv2=None, limit: int = 5000):
    return get_repo().capitoli(
        kind=kind, year=year, measure=measure, liv1=liv1, liv2=liv2, limit=limit)


@st.cache_data(ttl=300)
def capitoli_timeseries(*, kind: str, measure: str, capitolo_code=None,
                        liv1=None, liv2=None, liv3=None):
    return get_repo().capitoli_timeseries(
        kind=kind, measure=measure, capitolo_code=capitolo_code,
        liv1=liv1, liv2=liv2, liv3=liv3)


@st.cache_data(ttl=300)
def capitoli_distinct(*, kind: str, liv1: str, liv2=None, level: str = "capitolo"):
    return get_repo().capitoli_distinct(kind=kind, liv1=liv1, liv2=liv2, level=level)


@st.cache_data(ttl=300)
def debito(measure: str | None = None):
    return get_repo().debito(measure=measure)


@st.cache_data(ttl=300)
def debito_years():
    return get_repo().debito_years()


# Human labels for rendiconto measures.
RENDICONTO_MEASURES = {
    "spesa": {
        "impegni": "Impegni (competenza)",
        "pagamenti_totali": "Pagamenti (cassa)",
        "previsioni": "Previsioni definitive",
    },
    "entrata": {
        "accertamenti": "Accertamenti (competenza)",
        "riscossioni_totali": "Riscossioni (cassa)",
        "previsioni": "Previsioni definitive",
    },
}

# Plain-language definitions of each measure, shown next to the menu.
RENDICONTO_MEASURE_HELP = {
    "spesa": {
        "previsioni": "Stanziamento definitivo di bilancio: quanto l'ente era autorizzato "
                      "a spendere per la missione (comprende il fondo pluriennale vincolato).",
        "impegni": "Competenza: spese giuridicamente obbligate nell'anno (contratti e "
                   "obbligazioni assunte), anche se non ancora pagate.",
        "pagamenti_totali": "Cassa: denaro effettivamente uscito nell'anno, sia per impegni "
                            "dell'anno sia per debiti (residui) di anni precedenti.",
    },
    "entrata": {
        "previsioni": "Stanziamento definitivo di bilancio: quanto l'ente prevedeva di "
                      "incassare per il titolo.",
        "accertamenti": "Competenza: entrate giuridicamente accertate nell'anno (il diritto "
                        "a riscuotere è sorto), anche se non ancora incassate.",
        "riscossioni_totali": "Cassa: denaro effettivamente incassato nell'anno, sia di "
                              "competenza sia da crediti (residui) di anni precedenti.",
    },
}


def in_millions() -> bool:
    """Global display toggle: express all monetary values in millions of euro."""
    return bool(st.session_state.get("in_millions", False))


def scale_eur(v):
    """Scale a euro value for display according to the millions toggle."""
    if v is None:
        return None
    return v / 1e6 if in_millions() else v


def eur_unit() -> str:
    return "mln €" if in_millions() else "EUR"


def fmt_eur(v) -> str:
    if v is None:
        return "-"
    scaled = v / 1e6 if in_millions() else v
    body = f"{scaled:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{body} {eur_unit()}"


def fmt_value(v, unit: str) -> str:
    if v is None:
        return "-"
    if unit == "PCT":
        return f"{v:.2f}".replace(".", ",") + "%"
    return fmt_eur(v)


def _code_str(code) -> str:
    """Coerce a code cell (may be None or a NaN float from pandas) to a string."""
    if code is None or (isinstance(code, float) and code != code):
        return ""
    return str(code).strip()


def indent_voce(code, name) -> str:
    """Prefix a statement line with an indent reflecting its hierarchy depth.

    A single lowercase letter (a, b, c) is a sub-component of the numbered voce
    above it; a dotted code (1.1, 2.3) is a detail line. Both are indented.
    """
    code = _code_str(code)
    name = "" if name is None or (isinstance(name, float) and name != name) else str(name)
    depth = 0
    if len(code) == 1 and code.islower() and code.isalpha():
        depth = 2
    elif "." in code:
        depth = 1
    return " " * depth + (name or "")


# Conto economico sections. The section letter is printed on the *closing* row
# ("totale componenti positivi della gestione A)" ends section A); the rows above
# it are that section's voci, the rows below belong to the next section.
INCOME_SECTIONS = {
    "A": "A · Entrate (gestione)",
    "B": "B · Uscite (gestione)",
    "C": "C · Proventi e oneri finanziari",
    "D": "D · Rettifiche di valore attività finanziarie",
    "E": "E · Proventi e oneri straordinari",
}
_SECTION_LETTER = re.compile(r"\(?\s*([A-E])\s*\)")


def income_sections(names) -> list[str]:
    """Label each income-statement row with its section, derived from the
    section-closing ``totale ... A)`` / ``totale (C)`` rows.

    A "totale" whose text carries a bare section letter (A-E) closes that
    section: every row from the previous boundary up to and including it belongs
    to it. Rows after the last section total are the result block.
    """
    labels = [""] * len(names)
    start = 0
    found = False
    for i, n in enumerate(names):
        nm = "" if n is None or (isinstance(n, float) and n != n) else str(n)
        if not nm.lower().startswith("totale"):
            continue
        m = _SECTION_LETTER.search(nm)
        if not m:
            continue  # intermediate total (e.g. "Totale proventi finanziari")
        found = True
        label = INCOME_SECTIONS.get(m.group(1).upper(), "")
        for k in range(start, i + 1):
            labels[k] = label
        start = i + 1
    if found:
        for k in range(start, len(names)):
            labels[k] = "Risultato d'esercizio"
    return labels


# -- income-statement table with per-voce help tooltips -----------------------
_CE_STYLE = """
<style>
.ce-table{width:100%;border-collapse:collapse;font-size:0.9rem;}
.ce-table th{text-align:left;border-bottom:2px solid rgba(128,128,128,.4);
  padding:6px 10px;font-weight:600;}
.ce-table td{border-bottom:1px solid rgba(128,128,128,.18);padding:5px 10px;
  vertical-align:top;}
.ce-table td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}
.ce-table td.pag{text-align:right;color:#888;}
.ce-table tr.tot td{font-weight:700;background:rgba(128,128,128,.10);}
.ce-help{display:inline-block;margin-left:7px;width:15px;height:15px;line-height:15px;
  text-align:center;border-radius:50%;background:#3b82f6;color:#fff;font-size:11px;
  font-weight:700;cursor:help;position:relative;}
.ce-help .ce-tip{visibility:hidden;opacity:0;transition:opacity .15s ease;
  position:absolute;z-index:1000;left:22px;top:-6px;width:330px;background:#1f2937;
  color:#f9fafb;text-align:left;padding:10px 12px;border-radius:8px;font-size:12px;
  font-weight:400;line-height:1.45;box-shadow:0 6px 18px rgba(0,0,0,.30);
  white-space:normal;}
.ce-help:hover .ce-tip{visibility:visible;opacity:1;}
.ce-tip .src{display:block;margin-top:7px;font-size:11px;color:#9ca3af;}
</style>
"""


def _esc(text) -> str:
    s = "" if text is None or (isinstance(text, float) and text != text) else str(text)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_income_table(df) -> str:
    """Render the income statement as an HTML table where every voce that has a
    glossary entry carries a "?" icon; hovering it shows the plain-language
    description and its official source. Returns the HTML string."""
    head = ("<table class='ce-table'><thead><tr>"
            "<th>sezione</th><th>codice</th><th>voce</th>"
            "<th style='text-align:right'>valore</th>"
            "<th style='text-align:right'>pag.</th></tr></thead><tbody>")
    body = []
    for _, r in df.iterrows():
        code = _code_str(r["code"])
        name = "" if r["metric_name"] is None else str(r["metric_name"])
        depth = 2 if (len(code) == 1 and code.islower() and code.isalpha()) else (
            1 if "." in code else 0)
        is_tot = name.lower().startswith("totale") or "risultato" in name.lower() \
            or name.lower().startswith("differenza")
        voce_cell = ("<span style='padding-left:%dpx'>%s</span>"
                     % (depth * 16, _esc(name)))
        entry = glossary.lookup(name)
        if entry:
            desc, src = entry
            voce_cell += (
                "<span class='ce-help'>?"
                "<span class='ce-tip'>%s<span class='src'>Fonte: %s</span></span>"
                "</span>" % (_esc(desc), _esc(src)))
        body.append(
            "<tr class='%s'><td>%s</td><td>%s</td><td>%s</td>"
            "<td class='num'>%s</td><td class='pag'>%s</td></tr>" % (
                "tot" if is_tot else "",
                _esc(r.get("sezione", "")), _esc(code), voce_cell,
                _esc(r["valore"]), _esc(r["source_page"])))
    return _CE_STYLE + head + "".join(body) + "</tbody></table>"


# -- pages --------------------------------------------------------------------
def page_overview():
    st.header("Panoramica")
    st.caption(
        "Bilancio Consolidato del Comune di Torino - dati estratti dai PDF ufficiali, "
        "ogni valore tracciabile alla pagina di origine."
    )

    st.subheader("Indicatori chiave nel tempo")
    headline = [
        ("TOTALE DELL'ATTIVO", "balance_sheet_assets", "Totale Attivo"),
        ("TOTALE DEL PASSIVO", "balance_sheet_liabilities", "Totale Passivo"),
    ]
    for metric_name, category, label in headline:
        pts = [p for p in timeseries(metric_name, category) if p["value"] is not None]
        if not pts:
            continue
        df = pd.DataFrame(pts)
        if in_millions():
            yvals = [v / 1e6 for v in df["value"]]
            text = [f"{y:,.0f}" for y in yvals]
            ytitle = "mln €"
        else:
            yvals = [v / 1e9 for v in df["value"]]
            text = [f"{y:.2f} mld" for y in yvals]
            ytitle = "mld €"
        fig = go.Figure(go.Scatter(
            x=df["year"], y=yvals, mode="lines+markers+text",
            text=text, textposition="top center",
        ))
        fig.update_layout(title=label, height=320, margin=dict(t=40, b=10),
                          yaxis_title=ytitle, xaxis=dict(dtick=1))
        st.plotly_chart(fig, use_container_width=True)
        with st.expander(f"Fonti - {label}"):
            st.dataframe(df[["year", "value", "source_document", "source_page"]],
                         use_container_width=True, hide_index=True)

    st.subheader("Documenti registrati")
    st.dataframe(pd.DataFrame(documents()), use_container_width=True, hide_index=True)


def page_statements():
    st.header("Prospetti di bilancio")
    c1, c2 = st.columns(2)
    year = c1.selectbox("Anno", sorted(years(), reverse=True))
    category = c2.selectbox("Prospetto", categories(),
                            format_func=lambda c: CATEGORY_LABELS.get(c, c))
    rows = metrics(year=year, category=category, limit=2000)
    if not rows:
        st.info("Nessuna riga per questa selezione.")
        return
    # A past year appears in two documents (its own report and the next year's
    # prior-year column). Keep only the authoritative one (report year == year).
    doc_year = {d["filename"]: d["year"] for d in documents()}
    authoritative = [r for r in rows if doc_year.get(r["source_document"]) == year]
    if authoritative:
        rows = authoritative

    df = pd.DataFrame(rows)
    df["valore"] = df["value"].map(fmt_eur)
    # Indent sub-voci so the hierarchy reads like the PDF: a numbered voce
    # (e.g. 3) is followed by its lettered components (a, b, c) which sum to it.
    df["voce"] = [indent_voce(c, n) for c, n in zip(df["code"], df["metric_name"])]

    cols = ["code", "voce", "valore", "source_page"]
    is_income = category in ("income_statement", "aggregate_income_statement")
    # In the income statement A = Entrate and B = Uscite (C/D/E follow). Surface
    # the section of each row so every line is clearly an entrata or an uscita.
    if is_income:
        df["sezione"] = income_sections(df["metric_name"])
        cols = ["sezione"] + cols

    desc = CATEGORY_DESCRIPTIONS.get(category)
    if desc:
        st.info(desc)
    st.caption(f"{len(df)} righe · fonte: {df['source_document'].iloc[0]}")
    if is_income:
        # Render with per-voce "?" help tooltips (hover) explaining the major
        # line items in plain language, with their official source.
        st.caption("Passa il mouse sull'icona ❓ accanto a una voce per la spiegazione.")
        st.markdown(render_income_table(df), unsafe_allow_html=True)
    else:
        st.dataframe(
            df[cols].rename(columns={"code": "codice", "source_page": "pag."}),
            use_container_width=True, hide_index=True, height=560,
        )
    st.download_button("Scarica CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name=f"{category}_{year}.csv", mime="text/csv")


def page_comparison():
    st.header("Confronto tra anni")
    st.caption("Seleziona una voce di bilancio per vederne l'andamento pluriennale.")
    category = st.selectbox("Prospetto", categories(),
                            format_func=lambda c: CATEGORY_LABELS.get(c, c))
    rows = metrics(year=max(years()), category=category, limit=2000)
    names = sorted({r["metric_name"] for r in rows})
    if not names:
        st.info("Nessuna voce disponibile.")
        return
    default_idx = next((i for i, n in enumerate(names) if n.startswith("TOTALE")), 0)
    metric_name = st.selectbox("Voce", names, index=default_idx)
    pts = [p for p in timeseries(metric_name, category) if p["value"] is not None]
    if not pts:
        st.info("Nessun valore numerico per questa voce.")
        return
    df = pd.DataFrame(pts).sort_values("year")
    fig = go.Figure(go.Bar(x=df["year"], y=[scale_eur(v) for v in df["value"]],
                           text=[fmt_eur(v) for v in df["value"]], textposition="auto"))
    fig.update_layout(title=metric_name, height=380, yaxis_title=eur_unit(), xaxis=dict(dtick=1))
    st.plotly_chart(fig, use_container_width=True)
    if len(df) > 1:
        first, last = df.iloc[0], df.iloc[-1]
        if first["value"]:
            delta = (last["value"] - first["value"]) / first["value"] * 100
            st.metric(f"Variazione {int(first['year'])} -> {int(last['year'])}",
                      fmt_eur(last["value"] - first["value"]), f"{delta:+.1f}%")
    st.subheader("Fonti")
    st.dataframe(
        df[["year", "value", "source_document", "source_page"]].rename(
            columns={"year": "anno", "value": "valore", "source_page": "pag."}),
        use_container_width=True, hide_index=True)


def page_entities():
    st.header("Esplora le partecipate")
    directory = entity_directory()
    if not directory:
        st.info("Nessuna entità disponibile.")
        return
    names = {e["canonical_name"]: e["canonical_slug"] for e in directory}
    choice = st.selectbox("Entità", list(names))
    slug = names[choice]

    ent_rows = entities(slug=slug)
    if ent_rows:
        df = pd.DataFrame(ent_rows)
        st.subheader("Area di consolidamento")
        st.dataframe(
            df[["year", "name", "entity_type", "ownership_percentage", "source_page"]].rename(
                columns={"year": "anno", "name": "denominazione", "entity_type": "tipo",
                         "ownership_percentage": "quota %", "source_page": "pag."}),
            use_container_width=True, hide_index=True)

    # -- multi-year comparison of a per-entity metric -------------------------
    multiyear = entity_metrics_multiyear(slug)
    if multiyear:
        st.subheader("Andamento pluriennale")
        st.caption("Confronto tra anni per le metriche disponibili su più esercizi.")
        default_idx = multiyear.index("spesa_personale") if "spesa_personale" in multiyear else 0
        metric_name = st.selectbox(
            "Metrica", multiyear, index=default_idx, format_func=metric_label, key="ent_metric"
        )
        unit = "PCT" if metric_name in {
            "perc_consolidamento", "incidenza_ricavi_comune", "quota_posseduta"} else "EUR"

        # optional cross-entity overlay
        others = [e for e in entities_with_metric(metric_name) if e["canonical_slug"] != slug]
        other_names = {e["canonical_name"]: e["canonical_slug"] for e in others}
        compare = st.multiselect(
            "Confronta con altre partecipate", list(other_names),
            help="Sovrapponi l'andamento di altre entità sulla stessa metrica.")

        fig = go.Figure()
        all_pts = []
        for label_name, s in [(choice, slug)] + [(n, other_names[n]) for n in compare]:
            pts = [p for p in entity_metric_timeseries(s, metric_name) if p["value"] is not None]
            if not pts:
                continue
            d = pd.DataFrame(pts).sort_values("year")
            all_pts.append((label_name, d))
            yvals = d["value"] if unit == "PCT" else [scale_eur(v) for v in d["value"]]
            fig.add_trace(go.Scatter(
                x=d["year"], y=yvals, mode="lines+markers", name=label_name))
        if all_pts:
            ytitle = "%" if unit == "PCT" else eur_unit()
            fig.update_layout(title=metric_label(metric_name), height=380,
                              yaxis_title=ytitle, xaxis=dict(dtick=1),
                              legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)

            base = all_pts[0][1]
            if len(base) > 1:
                first, last = base.iloc[0], base.iloc[-1]
                delta_txt = "-"
                if first["value"]:
                    pct = (last["value"] - first["value"]) / abs(first["value"]) * 100
                    delta_txt = f"{pct:+.1f}%"
                st.metric(
                    f"{choice}: variazione {int(first['year'])} → {int(last['year'])}",
                    fmt_value(last["value"] - first["value"], unit), delta_txt)

            with st.expander("Fonti"):
                src = base[["year", "value", "source_document", "source_page"]].rename(
                    columns={"year": "anno", "value": "valore", "source_page": "pag."})
                st.dataframe(src, use_container_width=True, hide_index=True)

    em = entity_metrics(slug)
    if em:
        st.subheader("Tutti i dati per entità (personale, valutazione partecipazione)")
        dfm = pd.DataFrame(em)
        dfm["valore"] = [fmt_value(v, u) for v, u in zip(dfm["value"], dfm["unit"])]
        dfm["indicatore"] = dfm["metric_name"].map(metric_label)
        st.dataframe(
            dfm[["year", "source", "indicatore", "valore", "note", "source_page"]].rename(
                columns={"year": "anno", "source": "fonte", "note": "nota",
                         "source_page": "pag."}),
            use_container_width=True, hide_index=True, height=420)
    elif not ent_rows:
        st.info("Nessun dato per questa entità.")


def _rendiconto_label(code, name) -> str:
    c = _code_str(code)
    return f"{c} · {name}" if c else str(name)


# A 24-colour qualitative palette so ~20 stacked series stay visually distinct
# (the default 10-colour cycle repeated, making e.g. missione 15 and 99 collide).
_PALETTE = pcolors.qualitative.Dark24


def _voce_desc(kind: str, code) -> str:
    """Plain-language description of a missione/titolo (no source), or ''."""
    entry = glossary.missione_desc(code) if kind == "spesa" else glossary.titolo_desc(code)
    return entry[0] if entry else ""


def _hover_desc(kind: str, code) -> str:
    """Wrapped, HTML-safe description suffix for a plotly hover (or '')."""
    desc = _voce_desc(kind, code)
    if not desc:
        return ""
    # Escape the text first, then insert <br> tags plotly should render literally.
    wrapped = "<br>".join(textwrap.wrap(_esc(desc), 58))
    return f"<br><span style='font-size:11px'>{wrapped}</span>"


def _rendiconto_stacked(rows, measure_label: str, percent: bool, kind: str,
                        exclude_codes=(), net_base: bool = False):
    """Stacked bar chart: x = year, one stacked series per voce (missione/titolo).

    Each segment's hover shows the amount, its share of that year's total, and a
    plain-language description of the missione/titolo. ``exclude_codes`` are dropped
    from the chart; the share %% is computed on the total NET of those voci when
    ``net_base`` is set, otherwise on the full (gross) total -- so the user can read
    each voce against the budget with or without e.g. partite di giro.
    """
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("Nessun dato disponibile.")
        return
    df["voce"] = [_rendiconto_label(c, n) for c, n in zip(df["code"], df["name"])]
    exclude_codes = {str(c) for c in exclude_codes}
    kept = df[~df["code"].astype(str).isin(exclude_codes)]
    # % base: net of the excluded voci, or the full total (current default).
    year_total = (kept if net_base else df).groupby("year")["value"].sum().to_dict()
    df = kept
    if df.empty:
        st.info("Tutte le voci sono escluse.")
        return
    fig = go.Figure()
    # Order series by their most recent value so the legend/stack reads largest-first.
    last_year = df["year"].max()
    order = (df[df["year"] == last_year].sort_values("value", ascending=False)["voce"].tolist())
    order += [v for v in df["voce"].unique() if v not in order]
    for idx, voce in enumerate(order):
        d = df[df["voce"] == voce].sort_values("year")
        share = [v / year_total[y] * 100 if year_total.get(y) else 0
                 for y, v in zip(d["year"], d["value"])]
        desc_suffix = _hover_desc(kind, d["code"].iloc[0])
        fig.add_trace(go.Bar(
            x=d["year"], y=[scale_eur(v) for v in d["value"]], name=voce,
            marker_color=_PALETTE[idx % len(_PALETTE)],
            customdata=[[f"{s:.1f}"] for s in share],
            hovertemplate="<b>" + voce + "</b><br>%{y:,.0f} " + eur_unit()
            + " — %{customdata[0]}% del totale %{x}" + desc_suffix + "<extra></extra>"))
    fig.update_layout(
        barmode="stack", height=520, xaxis=dict(dtick=1, title=""),
        yaxis_title=("% sul totale" if percent else eur_unit()),
        legend=dict(orientation="v", font=dict(size=10)),
        hoverlabel=dict(align="left"),
        margin=dict(t=30, b=10), title=measure_label)
    if percent:
        fig.update_layout(barnorm="percent")
    st.plotly_chart(fig, use_container_width=True)


def _render_capitoli_detail(kind: str, measure: str, measure_label: str):
    """Optional, collapsed drill-down from a missione/titolo down to single
    capitoli: a zoomable treemap to explode the macro-areas plus a filtered table
    to reach the individual capitoli. Kept in an expander so the summary screens
    stay uncluttered. Has its own year selector (the analytic detail is available
    only for the years whose per-capitoli PDF has been ingested)."""
    cap_years = capitoli_years()
    with st.expander("🔍 Esplora il dettaglio per capitoli"):
        year = st.selectbox(
            "Anno (dettaglio analitico)", sorted(cap_years, reverse=True), key="cap_year",
            help="Il dettaglio per capitoli è disponibile per gli anni di cui è stato "
                 "caricato il rendiconto analitico.")
        root = "Spese" if kind == "spesa" else "Entrate"
        lab1 = "Missione" if kind == "spesa" else "Titolo"
        lab2 = "Programma" if kind == "spesa" else "Tipologia"
        lab3 = "Macroaggregato" if kind == "spesa" else "Categoria"
        st.caption(
            f"Dettaglio analitico {year}: ogni macroarea esplosa fino al singolo "
            f"capitolo di bilancio (misura: {measure_label.lower()}). Fonte: Conto di "
            "Bilancio D.Lgs 118 analitico per capitoli. I capitoli sommano esattamente "
            "agli aggregati per missione/titolo qui sopra.")
        leaf = capitoli(kind=kind, year=year, measure=measure, limit=100000)
        df = pd.DataFrame(leaf)
        if not df.empty:
            df = df[df["value"].astype(float) > 0].copy()
        if df.empty:
            st.info("Nessun importo positivo da mostrare per questa misura.")
            return
        df[lab1] = df["liv1_code"].astype(str) + " · " + df["liv1_name"].astype(str)
        df[lab2] = df["liv2_name"].fillna("—").astype(str)
        df[lab3] = df["liv3_name"].fillna("—").astype(str)
        # Capitolo leaf label: code + FULL denominazione (unique within parent).
        # The tile text is auto-clipped by plotly to fit, but the hover shows it in
        # full, so the complete name is readable on mouse-over.
        df["Capitolo"] = (df["capitolo_code"].astype(str) + " · "
                          + df["denominazione"].astype(str))
        df["val"] = [float(scale_eur(v)) for v in df["value"]]
        # Full path down to the single capitolo; maxdepth keeps the initial view at
        # the macro-area level and reveals capitoli on click (responsive with ~4k leaves).
        fig = px.treemap(
            df, path=[px.Constant(root), lab1, lab2, lab3, "Capitolo"], values="val",
            color=lab1, color_discrete_sequence=_PALETTE, maxdepth=4)
        fig.update_traces(
            root_color="lightgrey",
            textfont_size=17,
            hovertemplate="<b>%{label}</b><br>%{value:,.0f} " + eur_unit()
            + "<br>%{percentRoot} del totale<extra></extra>")
        # Fixed font (no uniformtext) => plotly keeps every label at 17px and shows
        # only the part that fits the tile, clipping the rest at the box edge (the
        # full name is always available on hover). Nothing is hidden.
        fig.update_layout(height=560, margin=dict(t=36, b=10),
                          title=f"{root} {year} · {measure_label} — clic per esplodere fino al capitolo")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Sono mostrati i primi livelli della gerarchia; **clicca un riquadro per "
            "zoomare** e scendere fino ai singoli capitoli di bilancio.")

        # -- drill-down table for one missione/titolo (+ optional programma) ----
        st.markdown(f"**Capitoli di una {lab1.lower()}**")
        opts = {f"{r['liv1_code']} · {r['liv1_name']}": r["liv1_code"]
                for r in capitoli_liv1(kind=kind, year=year)}
        c1, c2 = st.columns(2)
        pick1 = c1.selectbox(lab1, list(opts), key="cap_liv1")
        l1code = opts[pick1]
        sub = sorted({(r["liv2_code"], r["liv2_name"]) for r in leaf
                      if r["liv1_code"] == l1code and r["liv2_code"]},
                     key=lambda x: x[0] or "")
        sub_opts = {"Tutti": None} | {f"{c} · {n}": c for c, n in sub}
        pick2 = c2.selectbox(lab2, list(sub_opts), key="cap_liv2")
        rows = capitoli(kind=kind, year=year, measure=measure,
                        liv1=l1code, liv2=sub_opts[pick2])
        if not rows:
            st.info("Nessun capitolo per questa selezione.")
            return
        d = pd.DataFrame(rows)
        d["importo"] = d["value"].map(fmt_eur)
        view = d[["capitolo_code", "denominazione", "liv2_name", "liv3_name",
                  "importo", "source_page"]].rename(columns={
            "capitolo_code": "cod.", "denominazione": "capitolo",
            "liv2_name": lab2.lower(), "liv3_name": lab3.lower(),
            "source_page": "pag."})
        st.caption(f"{len(d)} capitoli · {measure_label.lower()} {year}")
        st.dataframe(view, use_container_width=True, hide_index=True, height=420)
        st.download_button(
            "Scarica capitoli (CSV)", d.to_csv(index=False).encode("utf-8"),
            file_name=f"capitoli_{kind}_{measure}_{year}.csv", mime="text/csv",
            key="dl_capitoli")

        # -- multi-year variation of a single capitolo / macroaggregato --------
        if len(cap_years) > 1:
            st.markdown("**Variazione negli anni**")
            st.caption(
                f"Andamento di {measure_label.lower()} sugli anni disponibili "
                f"({min(cap_years)}-{max(cap_years)}), entro la "
                f"{lab1.lower()} (ed eventuale {lab2.lower()}) selezionata sopra.")
            gran = st.radio(
                "Vedi l'andamento di:", ["Singolo capitolo", f"{lab3} (aggregato)"],
                horizontal=True, key="cap_trend_gran")
            level = "capitolo" if gran.startswith("Singolo") else "liv3"
            liv2_filter = sub_opts[pick2]
            items = capitoli_distinct(kind=kind, liv1=l1code, liv2=liv2_filter, level=level)
            if not items:
                st.info("Nessuna voce disponibile per questa selezione.")
                return
            choice = st.selectbox(
                "Voce", items, format_func=lambda it: f"{it['code']} · {it['name']}",
                key="cap_trend_item")
            if level == "capitolo":
                ts = capitoli_timeseries(kind=kind, measure=measure,
                                         capitolo_code=choice["code"])
            else:
                ts = capitoli_timeseries(kind=kind, measure=measure, liv1=l1code,
                                         liv2=liv2_filter, liv3=choice["code"])
            pts = [t for t in ts if t["value"] is not None]
            if not pts:
                st.info("Nessun importo per questa voce.")
                return
            tdf = pd.DataFrame(pts).sort_values("year")
            fig2 = go.Figure(go.Bar(
                x=tdf["year"], y=[scale_eur(v) for v in tdf["value"]],
                text=[fmt_eur(v) for v in tdf["value"]], textposition="outside",
                marker_color=_PALETTE[0],
                hovertemplate="<b>%{x}</b><br>%{y:,.0f} " + eur_unit() + "<extra></extra>"))
            fig2.update_layout(height=340, yaxis_title=eur_unit(), xaxis=dict(dtick=1),
                               margin=dict(t=34, b=10),
                               title=f"{choice['name'][:70]} — {measure_label}")
            st.plotly_chart(fig2, use_container_width=True)
            if len(tdf) > 1:
                first, last = tdf.iloc[0], tdf.iloc[-1]
                delta = last["value"] - first["value"]
                pct = (delta / first["value"] * 100) if first["value"] else 0
                st.metric(f"Variazione {int(first['year'])} → {int(last['year'])}",
                          fmt_eur(delta), f"{pct:+.1f}%")
            missing = [y for y in cap_years if y not in set(int(v) for v in tdf["year"])]
            if missing:
                st.caption("Nessun importo registrato per: "
                           + ", ".join(str(y) for y in missing) + ".")


def page_rendiconto():
    st.header("Rendiconto della gestione")
    if not rendiconto_years():
        st.info("Nessun rendiconto ingerito. Esegui `python -m src.etl.ingest` sui PDF dei rendiconti.")
        return
    st.info(
        "**Rendiconto della gestione (conto del bilancio)** — riguarda il **solo "
        "Comune di Torino** (non il Gruppo) ed è redatto su base **finanziaria**: "
        "registra, per ogni *missione* di spesa e *titolo* di entrata, gli stanziamenti "
        "(previsioni), gli **impegni**/**accertamenti** (competenza, cioè ciò che è "
        "stato giuridicamente obbligato o accertato nell'anno) e i **pagamenti**/"
        "**riscossioni** (cassa, cioè il denaro effettivamente movimentato). È un "
        "documento diverso dal bilancio consolidato: lì si misurano ricavi e costi di "
        "competenza economica dell'intero Gruppo (Comune + partecipate)."
    )

    yrs = rendiconto_years()
    c1, c2, c3 = st.columns([1.4, 1.4, 1])
    side = c1.radio("Vista", ["Spese (per missione)", "Entrate (per titolo)"], horizontal=False)
    kind = "spesa" if side.startswith("Spese") else "entrata"
    measures = RENDICONTO_MEASURES[kind]
    helps = RENDICONTO_MEASURE_HELP[kind]
    measure = c2.selectbox(
        "Misura", list(measures), format_func=lambda m: measures[m],
        index=list(measures).index("impegni" if kind == "spesa" else "accertamenti"),
        help="**Previsioni** = stanziamento autorizzato · **Competenza** "
             "(impegni/accertamenti) = obbligazioni sorte nell'anno · **Cassa** "
             "(pagamenti/riscossioni) = denaro effettivamente movimentato.")
    percent = c3.toggle("In %", help="Mostra la quota percentuale di ciascuna voce sul totale annuo.")
    with st.expander("Cosa indicano previsioni, competenza e cassa?"):
        for m, lbl in measures.items():
            st.markdown(f"- **{lbl}** — {helps[m]}")

    # -- optional exclusion of voci + percentage base --------------------------
    rows = rendiconto(kind=kind, measure=measure)
    voce_opts: dict[str, str] = {}
    for r in rows:
        voce_opts.setdefault(_rendiconto_label(r["code"], r["name"]), str(r["code"]))
    exclude_labels = st.multiselect(
        "Escludi voci dai grafici",
        sorted(voce_opts),
        help="Le voci selezionate spariscono dai grafici sottostanti. Utile per "
             "togliere partite di giro e anticipazioni di tesoreria, che gonfiano i "
             "totali senza essere vere entrate/spese.")
    exclude_codes = {voce_opts[lbl] for lbl in exclude_labels}
    net_base = st.toggle(
        "Percentuali sul totale al netto delle voci escluse",
        help="Se attivo, la quota %% di ogni voce è calcolata sul totale ESCLUSE le "
             "voci tolte sopra. Se disattivo, è calcolata sul totale che le comprende "
             "(comportamento predefinito).",
        disabled=not exclude_codes)

    # -- headline: incassi vs pagamenti for the latest year --------------------
    latest = max(yrs)
    inc = rendiconto_total(kind="entrata", measure="riscossioni_totali", year=latest)
    pag = rendiconto_total(kind="spesa", measure="pagamenti_totali", year=latest)
    if inc and pag:
        m1, m2, m3 = st.columns(3)
        m1.metric(f"Riscossioni {latest} (cassa)", fmt_eur(inc["value"]))
        m2.metric(f"Pagamenti {latest} (cassa)", fmt_eur(pag["value"]))
        saldo = inc["value"] - pag["value"]
        m3.metric(f"Saldo di cassa {latest}", fmt_eur(saldo),
                  help="Riscossioni meno pagamenti totali (competenza + residui).")
        st.caption(
            f"Fonte: {inc['source_document']}, pag. {inc['source_page']} (entrate) e "
            f"pag. {pag['source_page']} (spese).")

    # -- multi-year stacked composition ----------------------------------------
    st.subheader(f"Composizione nel tempo · {measures[measure]}")
    _rendiconto_stacked(rows, measures[measure], percent, kind, exclude_codes, net_base)

    # -- single-year ranked breakdown ------------------------------------------
    st.subheader("Dettaglio di un anno")
    year = st.selectbox("Anno", sorted(yrs, reverse=True))
    yr_rows = [r for r in rows if r["year"] == year and str(r["code"]) not in exclude_codes]
    if yr_rows:
        df = pd.DataFrame(yr_rows).sort_values("value", ascending=False)
        df["voce"] = [_rendiconto_label(c, n) for c, n in zip(df["code"], df["name"])]
        # % base: net of the excluded voci, or the full year total (default).
        net_tot = sum(r["value"] for r in yr_rows)
        gross_tot = sum(r["value"] for r in rows if r["year"] == year)
        tot = (net_tot if net_base else gross_tot) or 1
        df["quota"] = [f"{r['value'] / tot * 100:.1f}%" for _, r in df.iterrows()]
        df["importo"] = df["value"].map(fmt_eur)
        customdata = [[q, _hover_desc(kind, c)] for q, c in zip(df["quota"], df["code"])]
        fig = go.Figure(go.Bar(
            x=[scale_eur(v) for v in df["value"]], y=df["voce"], orientation="h",
            text=df["quota"], textposition="auto",
            marker_color=[_PALETTE[i % len(_PALETTE)] for i in range(len(df))],
            customdata=customdata,
            hovertemplate="<b>%{y}</b><br>%{x:,.0f} " + eur_unit()
            + " — %{customdata[0]} del totale" + "%{customdata[1]}<extra></extra>"))
        fig.update_layout(height=max(320, 26 * len(df)), xaxis_title=eur_unit(),
                          yaxis=dict(autorange="reversed"), margin=dict(t=10, b=10),
                          hoverlabel=dict(align="left"),
                          title=f"{measures[measure]} — {year}")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(
            df[["code", "name", "importo", "quota", "source_page"]].rename(
                columns={"code": "cod.", "name": "denominazione", "source_page": "pag."}),
            use_container_width=True, hide_index=True)
        st.download_button(
            "Scarica CSV", pd.DataFrame(rows).to_csv(index=False).encode("utf-8"),
            file_name=f"rendiconto_{kind}_{measure}.csv", mime="text/csv")

    # -- optional analytic drill-down to single capitoli -----------------------
    # Shown whenever any per-capitoli year exists (it has its own year selector);
    # the measure must be one the analytic detail carries.
    core = {"previsioni", "impegni", "pagamenti_totali", "accertamenti", "riscossioni_totali"}
    if capitoli_years() and measure in core:
        _render_capitoli_detail(kind, measure, measures[measure])


def _fmt_plain(v, dec: int = 0) -> str:
    """Italian-formatted number, NOT subject to the millions toggle (for
    per-capita euro and resident counts, which are small absolute figures)."""
    if v is None:
        return "-"
    body = f"{float(v):,.{dec}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return body


def page_debito():
    st.header("Debito del Comune")
    if not debito_years():
        st.info("Nessun dato sul debito caricato. Esegui `python -m src.etl.load_debito`.")
        return
    st.info(
        "**Debito del Comune di Torino** — è il debito finanziario dell'ente "
        "(mutui e prestiti). È una cosa diversa sia dal **bilancio consolidato** "
        "(che fotografa attività e passività dell'intero Gruppo, partecipate "
        "comprese) sia dal **rendiconto della gestione** (entrate e spese dell'anno): "
        "qui si guarda solo a quanto il Comune deve restituire e a quanto gli costa "
        "in interessi."
    )
    st.caption(
        "Dati 2018-2025 trascritti dalle tabelle delle **Relazioni del Collegio dei "
        "revisori dei conti** del Comune di Torino (evoluzione dell'indebitamento e "
        "oneri finanziari). Ogni riga riporta la relazione di origine."
    )

    rows = debito()
    by: dict[int, dict[str, float]] = {}
    src_by_year: dict[int, str] = {}
    for r in rows:
        by.setdefault(int(r["year"]), {})[r["measure"]] = r["value"]
        src_by_year[int(r["year"])] = r["source"]
    years = sorted(by)
    first, latest = years[0], years[-1]

    def col(measure):
        return [by[y].get(measure) for y in years]

    # -- headline -------------------------------------------------------------
    d_now = by[latest].get("debito_fine_anno")
    d_first = by[first].get("debito_fine_anno")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"Debito a fine {latest}", fmt_eur(d_now))
    if d_now is not None and d_first:
        delta = d_now - d_first
        pct = delta / d_first * 100
        m2.metric(f"Variazione dal {first}", fmt_eur(delta), f"{pct:+.1f}%",
                  delta_color="inverse",
                  help="Un calo del debito è positivo per i conti dell'ente.")
    pc = by[latest].get("debito_pro_capite")
    if pc is not None:
        m3.metric(f"Debito per abitante {latest}", f"{_fmt_plain(pc, 2)} €",
                  help="Debito a fine anno diviso il numero di residenti al 31/12.")
    on = by[latest].get("oneri_finanziari")
    if on is not None:
        m4.metric(f"Interessi {latest}", fmt_eur(on),
                  help="Oneri finanziari: gli interessi passivi pagati nell'anno sui prestiti.")

    # -- debt stock over time -------------------------------------------------
    st.subheader("Debito residuo a fine anno")
    stock = [(y, by[y].get("debito_fine_anno")) for y in years if by[y].get("debito_fine_anno") is not None]
    if stock:
        xs = [y for y, _ in stock]
        vals = [v for _, v in stock]
        fig = go.Figure(go.Bar(
            x=xs, y=[scale_eur(v) for v in vals],
            text=[fmt_eur(v) for v in vals], textposition="outside",
            marker_color=_PALETTE[0],
            hovertemplate="<b>%{x}</b><br>%{y:,.0f} " + eur_unit() + "<extra></extra>"))
        fig.update_layout(height=380, yaxis_title=eur_unit(), xaxis=dict(dtick=1),
                          margin=dict(t=20, b=10))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"Il debito è passato da {fmt_eur(stock[0][1])} ({stock[0][0]}) a "
            f"{fmt_eur(stock[-1][1])} ({stock[-1][0]}).")

    # -- annual flows: new loans vs repayments --------------------------------
    st.subheader("Flussi annuali: nuovi prestiti contro rimborsi")
    nuovi = col("nuovi_prestiti")
    rimb = col("prestiti_rimborsati")
    if any(v is not None for v in nuovi) or any(v is not None for v in rimb):
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=years, y=[scale_eur(v) for v in nuovi], name="Nuovi prestiti (+)",
            marker_color="#d97706",
            hovertemplate="<b>%{x}</b><br>Nuovi prestiti: %{y:,.0f} " + eur_unit() + "<extra></extra>"))
        fig.add_trace(go.Bar(
            x=years, y=[scale_eur(v) for v in rimb], name="Prestiti rimborsati (-)",
            marker_color="#2563eb",
            hovertemplate="<b>%{x}</b><br>Rimborsi: %{y:,.0f} " + eur_unit() + "<extra></extra>"))
        fig.update_layout(barmode="group", height=380, yaxis_title=eur_unit(),
                          xaxis=dict(dtick=1), margin=dict(t=20, b=10),
                          legend=dict(orientation="h", y=-0.18))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Quando i rimborsi superano i nuovi prestiti, il debito complessivo "
            "diminuisce. La quota capitale rimborsata coincide con i rimborsi qui sopra.")

    # -- interest and total debt service --------------------------------------
    st.subheader("Oneri finanziari e servizio del debito")
    oneri = col("oneri_finanziari")
    if any(v is not None for v in oneri):
        servizio = [
            (o + r) if (o is not None and r is not None) else None
            for o, r in zip(oneri, rimb)
        ]
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=years, y=[scale_eur(v) for v in oneri], name="Oneri finanziari (interessi)",
            marker_color="#dc2626",
            hovertemplate="<b>%{x}</b><br>Interessi: %{y:,.0f} " + eur_unit() + "<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=years, y=[scale_eur(v) for v in servizio], name="Servizio del debito (interessi + capitale)",
            mode="lines+markers", marker_color="#111827",
            hovertemplate="<b>%{x}</b><br>Servizio totale: %{y:,.0f} " + eur_unit() + "<extra></extra>"))
        fig.update_layout(height=380, yaxis_title=eur_unit(), xaxis=dict(dtick=1),
                          margin=dict(t=20, b=10), legend=dict(orientation="h", y=-0.18))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "**Oneri finanziari** = interessi passivi pagati nell'anno. **Servizio del "
            "debito** = interessi + quota capitale rimborsata, cioè l'esborso annuo "
            "complessivo per il debito.")

    # -- debt per resident ----------------------------------------------------
    pcs = [(y, by[y].get("debito_pro_capite")) for y in years if by[y].get("debito_pro_capite") is not None]
    if pcs:
        st.subheader("Debito medio per abitante")
        xs = [y for y, _ in pcs]
        vals = [v for _, v in pcs]
        fig = go.Figure(go.Bar(
            x=xs, y=[float(v) for v in vals],
            text=[f"{_fmt_plain(v, 0)} €" for v in vals], textposition="outside",
            marker_color=_PALETTE[2],
            hovertemplate="<b>%{x}</b><br>%{y:,.0f} € per abitante<extra></extra>"))
        fig.update_layout(height=340, yaxis_title="€ per abitante", xaxis=dict(dtick=1),
                          margin=dict(t=20, b=10))
        st.plotly_chart(fig, use_container_width=True)
        missing = [y for y in years if by[y].get("debito_pro_capite") is None]
        if missing:
            st.caption(
                "Dato non riportato nelle tabelle per: "
                + ", ".join(str(y) for y in missing) + ".")

    # -- full table + CSV -----------------------------------------------------
    st.subheader("Tutti i dati")
    table = {"misura": [DEBITO_MEASURES[m][0] for m in DEBITO_MEASURES]}
    for y in years:
        table[str(y)] = [
            (fmt_eur(by[y].get(m)) if DEBITO_MEASURES[m][1] == "EUR"
             else (f"{_fmt_plain(by[y].get(m), 2)} €" if DEBITO_MEASURES[m][1] == "EUR_AB"
                   else _fmt_plain(by[y].get(m), 0)))
            if by[y].get(m) is not None else "-"
            for m in DEBITO_MEASURES
        ]
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
    st.download_button(
        "Scarica CSV", pd.DataFrame(rows).to_csv(index=False).encode("utf-8"),
        file_name="debito_comune_torino.csv", mime="text/csv")

    with st.expander("Fonti"):
        for y in years:
            st.markdown(f"- **{y}** — {src_by_year[y]}")


def page_open_data():
    st.header("Dati aperti / per LLM")
    st.caption(
        "Questi dati sono pensati anche per essere letti da un assistente AI. "
        "Pubblica la cartella `site/` e indica all'LLM l'indirizzo del file `llms.txt`."
    )
    st.markdown(
        "**Come usarli con un modello come Claude / ChatGPT:**\n\n"
        "1. Pubblica la cartella statica generata con `make publish` (`site/`).\n"
        "2. Di' al modello: *\"Leggi i dati del Bilancio Consolidato del Comune di Torino "
        "su <indirizzo>/llms.txt e rispondi citando anno e pagina del PDF.\"*\n"
        "3. Ogni valore nei file pubblicati riporta documento e pagina di origine, "
        "così la risposta resta verificabile.\n\n"
        "I file disponibili (dopo la pubblicazione):\n"
        "- `llms.txt` - indice leggibile dai modelli\n"
        "- `index.html` e pagine per anno - numeri reali nell'HTML con citazioni\n"
        "- `data/*.json` e `data/*.csv` - dataset completi (metrics, entities, note, timeseries)\n"
    )
    st.info(
        "Genera/aggiorna i file con:  `make publish`  (oppure "
        "`python -m src.publish.build`). Anteprima locale:  `make serve-site`."
    )


PAGES = {
    "Prospetti di bilancio": page_statements,
    "Confronto tra anni": page_comparison,
    "Esplora le partecipate": page_entities,
    "Rendiconto della gestione": page_rendiconto,
    "Debito del Comune": page_debito,
    "Dati aperti / per LLM": page_open_data,
}


def main():
    repo = get_repo()
    yrs = repo.years()
    st.sidebar.title("📊 bilanciaTo")
    st.sidebar.caption("Bilancio Consolidato - Comune di Torino")
    choice = st.sidebar.radio("Sezioni", list(PAGES))
    st.sidebar.divider()
    st.sidebar.toggle(
        "Valori in milioni di €", key="in_millions",
        help="Esprime tutti gli importi in milioni di euro, riducendo le cifre.")
    st.sidebar.metric("Documenti", len(repo.documents()))
    st.sidebar.write("Anni: " + ", ".join(str(y) for y in yrs))
    PAGES[choice]()


main()
