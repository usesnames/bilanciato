"""Normalization of the *rendiconto della gestione* (conto del bilancio).

Unlike the bilancio consolidato (an accrual income statement / balance sheet of
the whole municipal group), the rendiconto is the **Comune di Torino alone**, on
a **finanziaria** basis: it tracks, per *missione* (spending area) and per
*titolo* (revenue category), the budget (previsioni), the accrual commitments
(impegni) / assessments (accertamenti), and the cash actually paid (pagamenti) /
collected (riscossioni).

We parse the two summary tables of the conto del bilancio (Allegato n.10):

* ``RIEPILOGO GENERALE DELLE SPESE PER MISSIONI`` -- one block per missione;
* ``RIEPILOGO GENERALE DELLE ENTRATE`` -- one block per titolo.

Each block prints its figures as *labelled* tokens (``CP 1.234,56  I 1.000,00``
...), three physical rows per record. The label set is fixed, so we parse by
label rather than by column position (robust to pdfplumber's per-page column
drift, and to large/negative numbers being glued to their label, e.g.
``CP-1.518.073.498,32``). The first occurrence of each label in a block is the
authoritative one (a few labels, e.g. ``CP``/``TR`` on the entrate side, recur
for the "maggiori/minori" and "residui" columns, which we do not keep).

Column legend (conto del bilancio):
  spese   CP=previsioni def. competenza  I=impegni  PC=pagamenti c/competenza
          TP=totale pagamenti (cassa)    FPV=fondo plur. vincolato
  entrate CP=previsioni def. competenza  A=accertamenti  RC=riscossioni c/comp.
          TR=totale riscossioni (cassa)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from src.utils.numbers import parse_euro


@dataclass
class RendicontoItem:
    """One (record x measure) figure of the conto del bilancio, long-format."""

    kind: str  # 'spesa' | 'entrata'
    level: str  # 'voce' | 'totale'
    code: str | None  # missione '01'..'99' / titolo '1'..'9'; None for the grand total
    name: str
    measure: str  # see _SPESA_MEASURES / _ENTRATA_MEASURES
    value: Decimal
    page: int


# Labels longest-first so e.g. ``ECP`` is not split into ``EC`` + ``P``.
_LABELS = sorted(
    {"ECP", "FPV", "RS", "PR", "EP", "CP", "PC", "EC", "CS", "TP", "TR", "RC", "RR", "A", "R", "I"},
    key=len,
    reverse=True,
)
_LAB_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(_LABELS) + r")\s*(-?[\d.]+,\d{2})")

# Measures kept per side: (output measure name, source label). Only the first
# occurrence of each label in a block is used (see module docstring).
_SPESA_MEASURES = (("previsioni", "CP"), ("impegni", "I"), ("pagamenti_totali", "TP"))
_ENTRATA_MEASURES = (("previsioni", "CP"), ("accertamenti", "A"), ("riscossioni_totali", "TR"))

_MISSIONE_RE = re.compile(r"^Missione\s+(\d+)\s+(.+?)\s+RS\s", re.S)
_TITOLO_RE = re.compile(r"^TITOLO\s+(\d+):\s+(.+?)\s+RS\s", re.S)


def _block_values(segment: str) -> dict[str, Decimal]:
    """First labelled value per label within a block (the authoritative column)."""
    out: dict[str, Decimal] = {}
    for m in _LAB_RE.finditer(segment):
        lab = m.group(1)
        if lab in out:
            continue
        val = parse_euro(m.group(2))
        if val is not None:
            out[lab] = val
    return out


def _split_records(pages: list[tuple[int, str]], start_markers: str):
    """Yield (page, block_text) for each record, split on the start markers.

    ``pages`` is a list of (1-based page number, page text). A record's page is
    the page on which it begins.
    """
    # Flatten to (page, line) so each record can be attributed to its first page.
    lines: list[tuple[int, str]] = []
    for page, text in pages:
        for ln in (text or "").splitlines():
            lines.append((page, ln))

    marker = re.compile(start_markers)
    cur_page: int | None = None
    buf: list[str] = []
    for page, ln in lines:
        if marker.match(ln.strip()):
            if buf:
                yield cur_page, "\n".join(buf)
            cur_page, buf = page, [ln]
        elif buf:
            buf.append(ln)
    if buf:
        yield cur_page, "\n".join(buf)


def normalize_spese_missioni(pages: list[tuple[int, str]]) -> list[RendicontoItem]:
    """Parse the per-missione spending summary into long-format items."""
    items: list[RendicontoItem] = []
    markers = r"(Missione\s+\d+|TOTALE MISSIONI|TOTALE GENERALE DELLE SPESE|DISAVANZO)"
    for page, block in _split_records(pages, r"^" + markers):
        seg = re.sub(r"\s+", " ", block).strip()
        vals = _block_values(seg)
        m = _MISSIONE_RE.match(seg)
        if m:
            code = m.group(1).zfill(2)
            name = m.group(2).strip()
            for measure, label in _SPESA_MEASURES:
                if label in vals:
                    items.append(RendicontoItem("spesa", "voce", code, name, measure, vals[label], page))
        elif seg.startswith("TOTALE GENERALE DELLE SPESE"):
            for measure, label in _SPESA_MEASURES:
                if label in vals:
                    items.append(
                        RendicontoItem("spesa", "totale", None, "Totale generale delle spese",
                                       measure, vals[label], page))
    return items


def normalize_entrate(pages: list[tuple[int, str]]) -> list[RendicontoItem]:
    """Parse the per-titolo revenue summary into long-format items."""
    items: list[RendicontoItem] = []
    markers = r"(TITOLO\s+\d+:|TOTALE DEI TITOLI|TOTALE GENERALE DELLE ENTRATE|FONDO|UTILIZZO)"
    for page, block in _split_records(pages, r"^" + markers):
        seg = re.sub(r"\s+", " ", block).strip()
        vals = _block_values(seg)
        m = _TITOLO_RE.match(seg)
        if m:
            code = m.group(1)
            name = m.group(2).strip()
            for measure, label in _ENTRATA_MEASURES:
                if label in vals:
                    items.append(RendicontoItem("entrata", "voce", code, name, measure, vals[label], page))
        elif seg.startswith("TOTALE GENERALE DELLE ENTRATE"):
            for measure, label in _ENTRATA_MEASURES:
                if label in vals:
                    items.append(
                        RendicontoItem("entrata", "totale", None, "Totale generale delle entrate",
                                       measure, vals[label], page))
    return items
