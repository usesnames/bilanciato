"""Indebitamento del Comune di Torino (curated dataset, 2018-2025).

Unlike the rest of the pipeline -- which extracts figures from the official PDFs
in ``uploads/`` -- this module holds a *curated* time series transcribed from
tables in the **Relazioni del Collegio dei revisori dei conti** of the Comune di
Torino (the bodies that certify each rendiconto). The user supplied screenshots of
those tables; the figures here are transcribed from them verbatim.

Two tables per relazione are used:

* *"L'indebitamento dell'ente ha avuto la seguente evoluzione"* -> residuo debito,
  nuovi prestiti, prestiti rimborsati (quota capitale), totale a fine anno, numero
  abitanti e debito medio per abitante;
* *"Gli oneri finanziari per ammortamento prestiti..."* -> oneri finanziari
  (interessi passivi) e quota capitale.

The data is internally consistent and was cross-checked (see ``validate_debito``):
the *debito a fine anno* of one year equals the *residuo debito* at the start of
the next, and *debito medio per abitante == debito a fine anno / abitanti*. The
relazioni overlap (each covers a 3-year window) and the overlapping years agree.

Because it is curated rather than PDF-extracted, it is loaded by a dedicated step
(``python -m src.etl.load_debito``) into the standalone ``debito`` table, with the
source relazione recorded on every row for traceability.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# -- provenance: the relazioni del Collegio dei revisori the figures come from ----
# Each relazione al rendiconto N reports the three-year window ending in N; the
# overlapping years (e.g. 2020) carry identical figures across relazioni.
SRC_REV_2020 = (
    "Relazione del Collegio dei revisori dei conti sul rendiconto 2020 - Comune di "
    "Torino (tabelle evoluzione dell'indebitamento e oneri finanziari)"
)
SRC_REV_2022 = (
    "Relazione del Collegio dei revisori dei conti sul rendiconto 2022 - Comune di "
    "Torino (tabelle evoluzione dell'indebitamento e oneri finanziari)"
)
SRC_REV_2025 = (
    "Relazione del Collegio dei revisori dei conti sul rendiconto 2025 - Comune di "
    "Torino (tabelle evoluzione dell'indebitamento e oneri finanziari)"
)

# Human labels + unit for every measure (drives the dashboard and exports).
#   EUR     monetary value in euro
#   ABITANTI resident headcount at 31/12
#   EUR_AB  euro per resident (debito medio per abitante)
DEBITO_MEASURES: dict[str, tuple[str, str]] = {
    "residuo_iniziale": ("Residuo debito a inizio anno", "EUR"),
    "nuovi_prestiti": ("Nuovi prestiti accesi nell'anno", "EUR"),
    "prestiti_rimborsati": ("Prestiti rimborsati (quota capitale)", "EUR"),
    "debito_fine_anno": ("Debito residuo a fine anno", "EUR"),
    "oneri_finanziari": ("Oneri finanziari (interessi passivi)", "EUR"),
    "abitanti": ("Abitanti al 31/12", "ABITANTI"),
    "debito_pro_capite": ("Debito medio per abitante", "EUR_AB"),
}

# Per-year figures, transcribed verbatim. ``None``/absent = not printed in the
# source table for that year. Exception: abitanti/pro-capite for 2021-2022 were
# missing (relazione screenshot cropped); they are derived from the popolazione
# table (Torino anagrafe, using 31/12 of the preceding year, consistent with all
# other years where this convention is verifiable).
_PER_YEAR: dict[int, dict[str, str]] = {
    2018: {
        "residuo_iniziale": "2824735021.48", "nuovi_prestiti": "16638609.39",
        "prestiti_rimborsati": "122016166.42", "debito_fine_anno": "2717422239.48",
        "oneri_finanziari": "69659833.34", "abitanti": "884733",
        "debito_pro_capite": "3071.46",
    },
    2019: {
        "residuo_iniziale": "2717422239.48", "nuovi_prestiti": "21399833.00",
        "prestiti_rimborsati": "124228202.31", "debito_fine_anno": "2613779408.24",
        "oneri_finanziari": "66790983.50", "abitanti": "879004",
        "debito_pro_capite": "2973.57",
    },
    2020: {
        "residuo_iniziale": "2613779408.24", "nuovi_prestiti": "55845903.02",
        "prestiti_rimborsati": "59763058.85", "debito_fine_anno": "2579249293.11",
        "oneri_finanziari": "66338429.52", "abitanti": "872316",
        "debito_pro_capite": "2956.78",
    },
    2021: {
        "residuo_iniziale": "2579249293.11", "nuovi_prestiti": "29866374.83",
        "prestiti_rimborsati": "95106421.31", "debito_fine_anno": "2512382937.30",
        "oneri_finanziari": "67633736.85",
        # abitanti/pro-capite were missing (relazione screenshot cropped); derived
        # from the popolazione table (Torino anagrafe 2020 = 866510, matching the
        # convention of all other years: use the 31/12 of the preceding year).
        "abitanti": "866510", "debito_pro_capite": "2899.43",
    },
    2022: {
        "residuo_iniziale": "2512382937.30", "nuovi_prestiti": "10500000.00",
        "prestiti_rimborsati": "109548971.97", "debito_fine_anno": "2413333965.80",
        "oneri_finanziari": "64205241.09",
        # abitanti/pro-capite derived from popolazione table (Torino anagrafe 2021
        # = 861636).
        "abitanti": "861636", "debito_pro_capite": "2800.87",
    },
    2023: {
        "residuo_iniziale": "2413333965.80", "nuovi_prestiti": "9998667.20",
        "prestiti_rimborsati": "115524764.80", "debito_fine_anno": "2307807868.20",
        "oneri_finanziari": "88109854.27", "abitanti": "858404",
        "debito_pro_capite": "2688.49",
    },
    2024: {
        "residuo_iniziale": "2307807868.20", "nuovi_prestiti": "9939143.39",
        "prestiti_rimborsati": "127777518.71", "debito_fine_anno": "2189969492.88",
        "oneri_finanziari": "87869766.81", "abitanti": "860973",
        "debito_pro_capite": "2543.60",
    },
    2025: {
        "residuo_iniziale": "2189969492.88", "nuovi_prestiti": "9998887.81",
        "prestiti_rimborsati": "125231462.10", "debito_fine_anno": "2074736918.59",
        "oneri_finanziari": "73443169.20", "abitanti": "862999",
        "debito_pro_capite": "2404.10",
    },
}

_SOURCE_BY_YEAR = {
    2018: SRC_REV_2020, 2019: SRC_REV_2020, 2020: SRC_REV_2020,
    2021: SRC_REV_2022, 2022: SRC_REV_2022,
    2023: SRC_REV_2025, 2024: SRC_REV_2025, 2025: SRC_REV_2025,
}


@dataclass
class DebitoItem:
    """One (year x measure) figure of the municipal-debt time series."""

    year: int
    measure: str
    value: Decimal
    unit: str
    source: str


def debito_items() -> list[DebitoItem]:
    """The curated debt series in long format (one item per year x measure)."""
    items: list[DebitoItem] = []
    for year in sorted(_PER_YEAR):
        source = _SOURCE_BY_YEAR[year]
        for measure, (_label, unit) in DEBITO_MEASURES.items():
            raw = _PER_YEAR[year].get(measure)
            if raw is None:
                continue
            items.append(DebitoItem(year, measure, Decimal(raw), unit, source))
    return items
