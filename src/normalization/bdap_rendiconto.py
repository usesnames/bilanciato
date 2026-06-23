"""Normalize the BDAP / RGS "Schemi di bilancio — Rendiconto" open-data CSVs into
the same long-format ``RendicontoItem`` as the PDF parser.

These are the authoritative open data published by the Ragioneria Generale dello
Stato (https://openbdap.rgs.mef.gov.it), one ZIP per region per year, containing
the harmonized (D.Lgs 118/2011) rendiconto schemes of *every* comune of that
region. We read the two per-region riepilogo files:

* ``... Spese Riepilogo Missioni ...``  — one row per (comune × missione), with
  ``Previsioni Definitive di Competenza``, ``Impegni`` and ``Totale Pagamenti``;
* ``... Entrate Riepilogo Titoli ...``  — one row per (comune × titolo), with
  ``Previsioni Definitive di Competenza``, ``Accertamenti`` and ``Totale Riscossioni``.

A single comune is selected by its ``Descrizione Comune`` (and the soggetto type
``COMUNI``, to exclude provinces/unions sharing the name). The grand total of each
measure is the sum of its voci, matching the per-missione/per-titolo semantics of
the PDF riepiloghi. Missioni/titoli that are entirely zero are omitted, as the PDF
riepiloghi omit them.

Number format is US-decimal: a dot decimal separator and **no** thousands
separator (e.g. ``1830430918.43``). The files are ``;``-separated and latin-1.

BDAP's "Previsioni Definitive di Competenza" is the per-missione/per-titolo
definitive forecast: it excludes the fondo pluriennale vincolato and the avanzo
di amministrazione applicato (which sit at the general level, not on a single
missione/titolo), so it is slightly lower than the PDF rendiconto's previsioni —
but it is internally consistent (voci sum to the total) and uniform across years.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

from src.normalization.rendiconto import RendicontoItem

# Soggetto type of an ordinary municipality (excludes provinces, unions, etc.
# that may share a "Descrizione Comune").
TIPOLOGIA_COMUNE = "COMUNI"

# Column -> measure name, per side. The keys are the exact BDAP header labels.
_SPESA_MEASURES = {
    "Previsioni Definitive di Competenza": "previsioni",
    "Impegni": "impegni",
    "Totale Pagamenti": "pagamenti_totali",
}
_ENTRATA_MEASURES = {
    "Previsioni Definitive di Competenza": "previsioni",
    "Accertamenti": "accertamenti",
    "Totale Riscossioni": "riscossioni_totali",
}


def _dec(s: str | None) -> Decimal:
    s = (s or "").strip()
    if not s:
        return Decimal(0)
    try:
        return Decimal(s)  # US-decimal: dot separator, no thousands grouping
    except InvalidOperation:
        return Decimal(0)


def load_riepilogo(data: bytes | str) -> tuple[list[str], list[list[str]]]:
    """Parse a BDAP riepilogo CSV (bytes or text) into ``(header, rows)``."""
    text = data.decode("latin-1") if isinstance(data, (bytes, bytearray)) else data
    reader = csv.reader(io.StringIO(text), delimiter=";")
    all_rows = [r for r in reader if r]
    if not all_rows:
        return [], []
    return [h.strip() for h in all_rows[0]], all_rows[1:]


def comune_rows(
    header: list[str], rows: list[list[str]], descrizione_comune: str
) -> list[list[str]]:
    """Select the rows of one comune (by ``Descrizione Comune`` + soggetto type)."""
    ci_com = header.index("Descrizione Comune")
    ci_tip = header.index("Descrizione Tipologia Soggetto")
    want = descrizione_comune.strip().upper()
    out = []
    for r in rows:
        if len(r) <= max(ci_com, ci_tip):
            continue
        if r[ci_com].strip().upper() == want and r[ci_tip].strip().upper() == TIPOLOGIA_COMUNE:
            out.append(r)
    return out


def _normalize_side(
    header: list[str],
    rows: list[list[str]],
    *,
    kind: str,
    code_col: str,
    name_col: str,
    measures: dict[str, str],
    norm_code,
    totale_name: str,
    names: dict[str, str] | None,
    page: int,
) -> list[RendicontoItem]:
    names = names or {}
    ci_code = header.index(code_col)
    ci_name = header.index(name_col)
    ci_meas = {col: header.index(col) for col in measures}

    items: list[RendicontoItem] = []
    totals: dict[str, Decimal] = {m: Decimal(0) for m in measures.values()}
    seen: dict[str, Decimal] = {}
    by_code: dict[str, tuple[str, dict[str, Decimal]]] = {}
    for r in rows:
        code = norm_code(r[ci_code].strip())
        vals = {measures[col]: _dec(r[idx]) for col, idx in ci_meas.items()}
        name = names.get(code) or r[ci_name].strip()
        prev = by_code.get(code)
        if prev is None:
            by_code[code] = (name, vals)
        else:  # a comune should appear once per missione/titolo; sum defensively
            for m, v in vals.items():
                prev[1][m] += v

    for code in sorted(by_code):
        name, vals = by_code[code]
        if all(v == 0 for v in vals.values()):
            continue
        for measure, value in vals.items():
            items.append(RendicontoItem(kind, "voce", code, name, measure, value, page))
            totals[measure] += value

    for measure in measures.values():
        items.append(RendicontoItem(kind, "totale", None, totale_name, measure, totals[measure], page))
    return items


def normalize_spese(
    header: list[str], rows: list[list[str]], *, names: dict[str, str] | None = None, page: int = 0
) -> list[RendicontoItem]:
    """Per-missione spese voci (+ grand total) for the already-selected comune rows.

    Missione codes are kept as BDAP prints them — zero-padded two digits
    (``01``..``99``), matching the PDF parser's spese codes.
    """
    return _normalize_side(
        header, rows, kind="spesa", code_col="Codice Missione",
        name_col="Descrizione Missione", measures=_SPESA_MEASURES,
        norm_code=lambda c: c, totale_name="Totale generale delle spese",
        names=names, page=page,
    )


def normalize_entrate(
    header: list[str], rows: list[list[str]], *, names: dict[str, str] | None = None, page: int = 0
) -> list[RendicontoItem]:
    """Per-titolo entrate voci (+ grand total) for the already-selected comune rows.

    Titolo codes are normalized to a single digit (``1``..``9``) to match the PDF
    parser's entrate codes (BDAP prints them zero-padded, ``01``..``09``).
    """
    return _normalize_side(
        header, rows, kind="entrata", code_col="Codice Titolo",
        name_col="Descrizione Titolo", measures=_ENTRATA_MEASURES,
        norm_code=lambda c: str(int(c)) if c.isdigit() else c,
        totale_name="Totale generale delle entrate", names=names, page=page,
    )
