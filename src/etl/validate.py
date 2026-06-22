"""Validation layer.

Checks accounting consistency on the normalized data. Validation errors are
never silently ignored (CLAUDE.md): they are collected into a report that is
persisted alongside the normalized output and surfaced by the ingest CLI.

The headline identity for a balance sheet is Attivo = Passivo (in the Italian
financial-accounting schema, the passivo total already includes net equity, so
the identity is simply TOTALE DELL'ATTIVO == TOTALE DEL PASSIVO).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from collections import defaultdict

from src.normalization.note_tables import NoteItem
from src.normalization.rendiconto import RendicontoItem
from src.normalization.statements import NormalizedRow


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def _find(rows, matcher, use_current: bool, table_types: set[str]) -> Decimal | None:
    for r in rows:
        if r.table_type in table_types and matcher(r.description.lower().strip()):
            return r.value_2024 if use_current else r.value_2023
    return None


def _identity_check(
    rows: list[NormalizedRow], name: str, use_current: bool, table_types: set[str]
) -> Check:
    attivo = _find(rows, lambda d: d.startswith("totale dell'attivo"), use_current, table_types)
    # The passivo grand total is sometimes printed as a bare "TOTALE DEL"
    # (the word PASSIVO wraps onto the section-header row). Within the
    # liabilities section "totale del..." can only be that grand total.
    passivo = _find(
        rows,
        lambda d: d.startswith("totale del") and "attivo" not in d,
        use_current,
        table_types,
    )
    if attivo is None or passivo is None:
        return Check(name, False, f"missing total(s): attivo={attivo}, passivo={passivo}")
    return Check(name, attivo == passivo,
                 f"attivo={attivo} passivo={passivo} delta={attivo - passivo}")


# Consolidated statements carry the current + prior year; the aggregate is
# single-valued (current year only). value_2024/value_2023 on a NormalizedRow
# are the current/prior columns regardless of the document's actual year.
_CONSOLIDATED = {"balance_sheet_assets", "balance_sheet_liabilities"}
_AGGREGATE = {"aggregate_balance_sheet_assets", "aggregate_balance_sheet_liabilities"}


def validate(rows: list[NormalizedRow], year: int) -> list[Check]:
    """Run accounting-consistency checks over all normalized rows.

    ``year`` is the document's reporting year; the prior column is ``year - 1``.
    """
    checks: list[Check] = []

    # Consolidated balance sheet: Attivo = Passivo, current and prior year.
    checks.append(
        _identity_check(rows, f"balance_sheet_identity_{year}", True, _CONSOLIDATED)
    )
    checks.append(
        _identity_check(rows, f"balance_sheet_identity_{year - 1}", False, _CONSOLIDATED)
    )

    # Pre-consolidation aggregate: Attivo = Passivo (single provisional column).
    if any(r.table_type in _AGGREGATE for r in rows):
        checks.append(
            _identity_check(rows, "aggregate_balance_sheet_identity", True, _AGGREGATE)
        )

    # No malformed numeric values: every metric row must have a parsed value.
    bad = [r for r in rows if r.is_metric and r.value_2024 is None]
    checks.append(
        Check("no_malformed_metric_values", not bad, f"{len(bad)} malformed rows")
    )

    return checks


_SINGLE_LETTER = re.compile(r"[a-z]")


def validate_statement_subtotals(rows: list[NormalizedRow]) -> list[Check]:
    """Check the line-item hierarchy: a numbered voce equals the sum of its
    immediately-following lettered sub-voci (a, b, c, ...).

    In these statements a lowercase-letter code marks a component of the
    preceding numbered line (e.g. "3 Proventi da trasferimenti e contributi" =
    a + b + c). Summing them and comparing to the parent catches a dropped or
    misread line item -- exactly the failure mode of a wrong page range.

    "di cui" rows are *of which* annotations (a partial highlight, not an
    additive breakdown) and are excluded. The check runs per statement section,
    in extraction order, on the current-year column.
    """
    by_type: dict[str, list[NormalizedRow]] = defaultdict(list)
    for r in rows:
        by_type[r.table_type].append(r)

    checked = 0
    mismatches: list[tuple[str, Decimal]] = []
    for rs in by_type.values():
        i = 0
        while i < len(rs):
            parent = rs[i]
            j = i + 1
            subs: list[NormalizedRow] = []
            # Collect the parent's lettered sub-voci. A repeated column header at
            # a page break (no value, no code) can sit between two sub-voci, so
            # such interstitial rows are skipped rather than ending the group.
            while j < len(rs):
                rj = rs[j]
                is_letter = bool(_SINGLE_LETTER.fullmatch(rj.code or ""))
                if rj.value_2024 is None and not is_letter:
                    j += 1  # header / noise row between sub-voci
                    continue
                if is_letter and not rj.description.lower().startswith("di cui"):
                    subs.append(rj)
                    j += 1
                    continue
                break  # the next numbered line item ends the group
            if subs and parent.value_2024 is not None and all(
                s.value_2024 is not None for s in subs
            ):
                checked += 1
                delta = parent.value_2024 - sum(s.value_2024 for s in subs)
                if abs(delta) > Decimal("0.05"):
                    mismatches.append((parent.description[:40], delta))
            i = j if subs else i + 1

    detail = "; ".join(f"{d}: Δ={x}" for d, x in mismatches[:5]) or "all consistent"
    return [
        Check(
            "statement_subtotals",
            not mismatches,
            f"{checked} numbered voci checked against their sub-voci, "
            f"{len(mismatches)} mismatched. {detail}",
        )
    ]


_INTEGER_CODE = re.compile(r"\d+")
_INCOME_TYPES = {"income_statement", "aggregate_income_statement"}


def validate_gestione_totals(rows: list[NormalizedRow]) -> list[Check]:
    """Check the income-statement section totals for *gestione* (A and B).

    The first column marks with an uppercase ``A`` / ``B`` the start of the
    revenue (Entrate) and cost (Uscite) sections of the gestione. Each section's
    printed "totale componenti ... della gestione" equals the sum of its
    numbered voci. (Sections C/D/E are *net* results, not simple sums, so they
    are intentionally not reconciled here.)
    """
    by_type: dict[str, list[NormalizedRow]] = defaultdict(list)
    for r in rows:
        if r.table_type in _INCOME_TYPES:
            by_type[r.table_type].append(r)

    checked = 0
    mismatches: list[tuple[str, Decimal]] = []
    for rs in by_type.values():
        section: str | None = None
        acc = Decimal(0)
        for r in rs:
            code = (r.code or "").strip()
            desc = r.description.lower()
            if code in ("A", "B"):
                section, acc = code, Decimal(0)
                continue
            if section is None:
                continue
            if _INTEGER_CODE.fullmatch(code) and r.value_2024 is not None:
                acc += r.value_2024
            if desc.startswith("totale") and "gestione" in desc and r.value_2024 is not None:
                checked += 1
                if abs(r.value_2024 - acc) > Decimal("0.05"):
                    mismatches.append((r.description[:40], r.value_2024 - acc))
                section, acc = None, Decimal(0)

    detail = "; ".join(f"{d}: Δ={x}" for d, x in mismatches[:5]) or "all consistent"
    return [
        Check(
            "income_gestione_totals",
            not mismatches,
            f"{checked} sezioni A/B (gestione) verificate, {len(mismatches)} non quadrano. {detail}",
        )
    ]


def validate_note_items(items: list[NoteItem]) -> list[Check]:
    """Check movement-table identity: inizio + variazione == fine, per voce.

    A mismatch usually signals a misaligned column or a merged row, so it is
    reported rather than ignored. A small tolerance absorbs cent-level rounding.
    """
    by_voce: dict[tuple, dict[str, Decimal]] = defaultdict(dict)
    for it in items:
        if it.kind == "movimenti":
            by_voce[(it.page, it.table_index, it.voce)][it.period] = it.value

    mismatches = []
    checked = 0
    for key, periods in by_voce.items():
        if {"inizio", "variazione", "fine"} <= periods.keys():
            checked += 1
            delta = periods["inizio"] + periods["variazione"] - periods["fine"]
            if abs(delta) > Decimal("0.05"):
                mismatches.append((key[2], delta))

    detail = "; ".join(f"{v}: Δ={d}" for v, d in mismatches[:5]) or "all consistent"
    return [
        Check(
            "note_movements_identity",
            not mismatches,
            f"{checked} movement rows checked, {len(mismatches)} mismatched. {detail}",
        )
    ]


def validate_rendiconto_totals(items: list[RendicontoItem]) -> list[Check]:
    """Check that, per kind and measure, the sum of the voci equals the printed
    grand total ("TOTALE GENERALE DELLE ENTRATE/SPESE").

    Only the accrual/cash measures are reconciled (accertamenti, riscossioni_totali
    for entrate; impegni, pagamenti_totali for spese): the previsioni grand total
    also folds in disavanzo/avanzo and FPV rows that are not per-voce, so it is
    intentionally not summed here.
    """
    reconciled = {
        "entrata": ("accertamenti", "riscossioni_totali"),
        "spesa": ("impegni", "pagamenti_totali"),
    }
    voce_sum: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal(0))
    totals: dict[tuple[str, str], Decimal] = {}
    for it in items:
        if it.value is None:
            continue
        if it.level == "voce":
            voce_sum[(it.kind, it.measure)] += it.value
        elif it.level == "totale":
            totals[(it.kind, it.measure)] = it.value

    checked = 0
    mismatches: list[tuple[str, Decimal]] = []
    for kind, measures in reconciled.items():
        for measure in measures:
            key = (kind, measure)
            if key not in totals:
                continue
            checked += 1
            delta = voce_sum[key] - totals[key]
            if abs(delta) > Decimal("0.05"):
                mismatches.append((f"{kind}/{measure}", delta))

    detail = "; ".join(f"{k}: Δ={d}" for k, d in mismatches) or "all consistent"
    return [
        Check(
            "rendiconto_totals",
            not mismatches and checked > 0,
            f"{checked} totali (voci vs totale generale) verificati, "
            f"{len(mismatches)} non quadrano. {detail}",
        )
    ]


def save_report(out_dir: Path, checks: list[Check]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "passed": all(c.passed for c in checks),
        "checks": [asdict(c) for c in checks],
    }
    path = out_dir / "validation_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return path
