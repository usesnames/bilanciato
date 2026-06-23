"""Normalize the Comune di Torino *rendiconto della gestione* "Formato aperto"
CSVs into the same long-format ``RendicontoItem`` as the PDF parser.

Used for years whose official PDF is unusable -- 2019's rendiconto is only
available as a poor scan -- but which the Comune also publishes as open-data CSVs.
The CSVs carry the accrual commitments/assessments (impegni / accertamenti) and
the cash paid/collected (pagamenti / riscossioni) but NOT the previsioni
(definitive forecasts), so a CSV-sourced year has those four measures only.

Layouts (semicolon-separated, latin-1 encoded):

* entrate -- ``Titolo;Tipologia;Accertamenti;Riscossioni`` (one row per tipologia,
  plus ``TOTALE TITOLO``/``TOTALE TITOLI``/``TOTALE GENERALE`` rows and the
  FPV/avanzo rows at the top). We aggregate the tipologie up to the titolo.

* spese -- ``Titolo;Macroaggregato; <missione> Impegnato; <missione> FPV;
  <missione> Pagato; ...`` for 23 missioni, then ``Ripiano disavanzo Competenza``
  and ``Totale generale delle spese {Impegnato,FPV,Pagato}``. It is a
  macroaggregato x missione matrix; the per-missione column totals are printed on
  the ``TOTALE MISSIONI - TOTALE GENERALE DELLE SPESE`` row, which we read directly.

To stay consistent with the PDF-sourced years, the entrate grand total is the sum
of the titoli (the CSV's ``TOTALE TITOLI``), excluding the FPV/avanzo rows -- in
the conto del bilancio those have a previsione but no accertamento. Missioni/titoli
that are entirely zero are omitted, as the PDF riepiloghi omit them.
"""

from __future__ import annotations

import csv
import re
from decimal import Decimal
from pathlib import Path

from src.normalization.rendiconto import RendicontoItem

# The 23 missioni in the fixed column order of the spese "Formato aperto" CSV,
# as their canonical D.Lgs 118 codes (zero-padded to match the rendiconto table).
_SPESA_MISSIONE_CODES = [
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12",
    "13", "14", "15", "16", "17", "18", "19", "20", "50", "60", "99",
]

_TITOLO_RE = re.compile(r"^(\d+)\s*-\s*(.+)$")


def _dec(s: str | None) -> Decimal:
    s = (s or "").strip()
    return Decimal(s.replace(".", "").replace(",", ".")) if s else Decimal(0)


def normalize_entrate_csv(path: str | Path, *, page: int = 0) -> list[RendicontoItem]:
    """Aggregate the per-tipologia entrate CSV up to per-titolo voci + grand total."""
    with open(path, encoding="latin-1", newline="") as fh:
        rows = list(csv.reader(fh, delimiter=";"))

    # code -> [name, accertamenti, riscossioni], summing the tipologie of each titolo.
    titoli: dict[str, list] = {}
    for r in rows[1:]:
        if len(r) < 4:
            continue
        m = _TITOLO_RE.match(r[0].strip())
        if not m or not r[1].strip().upper().startswith("TIPOLOGIA"):
            continue  # skip FPV/avanzo rows, TOTALE rows, blank rows
        code, name = m.group(1), m.group(2).strip()
        t = titoli.setdefault(code, [name, Decimal(0), Decimal(0)])
        t[1] += _dec(r[2])
        t[2] += _dec(r[3])

    items: list[RendicontoItem] = []
    for code in sorted(titoli, key=int):
        name, acc, risc = titoli[code]
        if acc == 0 and risc == 0:
            continue
        items.append(RendicontoItem("entrata", "voce", code, name, "accertamenti", acc, page))
        items.append(RendicontoItem("entrata", "voce", code, name, "riscossioni_totali", risc, page))

    tot_acc = sum((t[1] for t in titoli.values()), Decimal(0))
    tot_risc = sum((t[2] for t in titoli.values()), Decimal(0))
    items.append(RendicontoItem("entrata", "totale", None, "Totale generale delle entrate", "accertamenti", tot_acc, page))
    items.append(RendicontoItem("entrata", "totale", None, "Totale generale delle entrate", "riscossioni_totali", tot_risc, page))
    return items


def normalize_spese_csv(
    path: str | Path, *, missione_names: dict[str, str], page: int = 0
) -> list[RendicontoItem]:
    """Read the per-missione column totals (impegni, pagamenti) from the spese CSV."""
    with open(path, encoding="latin-1", newline="") as fh:
        rows = list(csv.reader(fh, delimiter=";"))

    tot_rows = [r for r in rows if r and r[0].strip().startswith("TOTALE MISSIONI")]
    if not tot_rows:
        raise ValueError("spese CSV: 'TOTALE MISSIONI' row not found")
    cells = tot_rows[0][2:]  # 23 missioni x (Impegnato, FPV, Pagato) then Ripiano + grand totals

    items: list[RendicontoItem] = []
    for i, code in enumerate(_SPESA_MISSIONE_CODES):
        imp = _dec(cells[i * 3 + 0])
        pag = _dec(cells[i * 3 + 2])
        if imp == 0 and pag == 0:
            continue
        name = missione_names.get(code, f"Missione {int(code)}")
        items.append(RendicontoItem("spesa", "voce", code, name, "impegni", imp, page))
        items.append(RendicontoItem("spesa", "voce", code, name, "pagamenti_totali", pag, page))

    # Grand totals: after the 69 missione columns come "Ripiano disavanzo
    # Competenza" (index 69) and "Totale generale delle spese" Impegnato/FPV/Pagato
    # (70/71/72).
    n = len(_SPESA_MISSIONE_CODES) * 3
    gt_imp = _dec(cells[n + 1])
    gt_pag = _dec(cells[n + 3])
    items.append(RendicontoItem("spesa", "totale", None, "Totale generale delle spese", "impegni", gt_imp, page))
    items.append(RendicontoItem("spesa", "totale", None, "Totale generale delle spese", "pagamenti_totali", gt_pag, page))
    return items
