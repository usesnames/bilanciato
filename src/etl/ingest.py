"""Ingestion orchestrator.

Pipeline (CLAUDE.md "Ingestion Workflow"):

    1. detect document type   -- via the filename -> profile registry
    2. detect year            -- from the profile
    3. compute checksum       -- sha256, prevents duplicate imports
    4. extract tables         -- pdfplumber, raw rows saved to extracted/
    5. normalize data         -- typed rows saved to normalized/
    6. validate consistency   -- Attivo = Passivo, report saved
    7. load into DuckDB        -- documents / tables / metrics

Usage:
    python -m src.etl.ingest                 # all profiled PDFs in uploads/
    python -m src.etl.ingest <file.pdf>      # a single PDF (path or basename)
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

from src.database import load
from src.database.schema import connect, init_schema
from src.etl import validate
from src.extraction.pdf_tables import (
    ExtractedSection,
    extract_entity_rows,
    extract_note_tables,
    extract_section,
    save_raw,
)
from src.normalization.entities import Entity, normalize_entities
from src.normalization.entity_financials import (
    EntityMetric,
    normalize_personnel,
    normalize_personnel_paired,
    normalize_valuation,
    normalize_valuation_paired,
)
from src.normalization.note_tables import NoteItem, normalize_note_tables
from src.normalization.rendiconto import (
    RendicontoItem,
    normalize_entrate,
    normalize_spese_missioni,
)
from src.normalization.statements import NormalizedRow, normalize_section
from src.utils.config import (
    EXTRACTED,
    NORMALIZED,
    PROFILES,
    RENDICONTO_PROFILES,
    UPLOADS,
)


def _checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _save_normalized(doc_name: str, rows: list[NormalizedRow]) -> Path:
    out_dir = NORMALIZED / doc_name
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "statements.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["table_type", "page", "code", "description", "value_2024", "value_2023", "is_metric"]
        )
        for r in rows:
            w.writerow(
                [r.table_type, r.page, r.code, r.description,
                 r.value_2024 if r.value_2024 is not None else "",
                 r.value_2023 if r.value_2023 is not None else "",
                 r.is_metric]
            )
    return out_dir


def _save_entities(doc_name: str, entities: list[Entity]) -> None:
    """Persist entities: raw (with quota text) to extracted/, typed to normalized/."""
    (EXTRACTED / doc_name).mkdir(parents=True, exist_ok=True)
    (EXTRACTED / doc_name / "entities.json").write_text(
        json.dumps([asdict(e) for e in entities], ensure_ascii=False, indent=2, default=str)
    )
    out = NORMALIZED / doc_name
    out.mkdir(parents=True, exist_ok=True)
    with (out / "entities.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "entity_type", "ownership_percentage", "consolidation_method", "page"])
        for e in entities:
            w.writerow([e.name, e.entity_type,
                        e.ownership_percentage if e.ownership_percentage is not None else "",
                        e.consolidation_method or "", e.page])


def _save_entity_metrics(doc_name: str, metrics: list[EntityMetric]) -> None:
    """Persist long-format per-entity figures to extracted/ and normalized/."""
    (EXTRACTED / doc_name).mkdir(parents=True, exist_ok=True)
    (EXTRACTED / doc_name / "entity_metrics.json").write_text(
        json.dumps([asdict(m) for m in metrics], ensure_ascii=False, indent=2, default=str)
    )
    out = NORMALIZED / doc_name
    out.mkdir(parents=True, exist_ok=True)
    with (out / "entity_metrics.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["entity_name", "source", "metric_name", "value", "unit", "note", "page"])
        for m in metrics:
            w.writerow([m.entity_name, m.source, m.metric_name,
                        m.value if m.value is not None else "", m.unit, m.note or "", m.page])


def _save_note_items(doc_name: str, items: list[NoteItem]) -> None:
    """Persist long-format nota integrativa items to extracted/ and normalized/."""
    (EXTRACTED / doc_name).mkdir(parents=True, exist_ok=True)
    (EXTRACTED / doc_name / "note_items.json").write_text(
        json.dumps([asdict(it) for it in items], ensure_ascii=False, indent=2, default=str)
    )
    out = NORMALIZED / doc_name
    out.mkdir(parents=True, exist_ok=True)
    with (out / "note_items.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["page", "table_index", "heading", "kind", "voce", "period", "value", "unit"])
        for it in items:
            w.writerow([it.page, it.table_index, it.heading, it.kind, it.voce,
                        it.period, it.value if it.value is not None else "", it.unit])


def _save_rendiconto(doc_name: str, items: list[RendicontoItem]) -> None:
    """Persist long-format rendiconto items to extracted/ and normalized/."""
    (EXTRACTED / doc_name).mkdir(parents=True, exist_ok=True)
    (EXTRACTED / doc_name / "rendiconto.json").write_text(
        json.dumps([asdict(it) for it in items], ensure_ascii=False, indent=2, default=str)
    )
    out = NORMALIZED / doc_name
    out.mkdir(parents=True, exist_ok=True)
    with (out / "rendiconto.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["kind", "level", "code", "name", "measure", "value", "page"])
        for it in items:
            w.writerow([it.kind, it.level, it.code or "", it.name, it.measure,
                        it.value if it.value is not None else "", it.page])


def ingest_rendiconto(pdf_path: Path) -> bool:
    """Ingest a rendiconto della gestione (conto del bilancio summary tables)."""
    doc_name = pdf_path.name
    profile = RENDICONTO_PROFILES[doc_name]
    print(f"==> {doc_name}")
    checksum = _checksum(pdf_path)
    print(f"    type={profile.document_type} year={profile.year} sha256={checksum[:12]}...")

    con = connect()
    init_schema(con)
    existing = load.document_exists(con, checksum)
    if existing is not None:
        print(f"    already imported (document id={existing}) -- skipping")
        con.close()
        return False

    def _pages(rng: tuple[int, int]) -> list[tuple[int, str]]:
        return [(p, pdf.pages[p - 1].extract_text() or "")
                for p in range(rng[0], rng[1] + 1)]

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        items = (normalize_entrate(_pages(profile.entrate_pages))
                 + normalize_spese_missioni(_pages(profile.spese_missioni_pages)))

    _save_rendiconto(doc_name, items)
    n_voci = sum(1 for it in items if it.level == "voce")
    print(f"    extracted {len(items)} rendiconto items ({n_voci} voci)")

    checks = validate.validate_rendiconto_totals(items)
    report_path = validate.save_report(NORMALIZED / doc_name, checks)
    for c in checks:
        print(f"    [{'OK ' if c.passed else 'FAIL'}] {c.name}: {c.detail}")
    if not all(c.passed for c in checks):
        print(f"    validation FAILED -- see {report_path}; not loading into DuckDB")
        con.close()
        return False

    doc_id = load.insert_document(
        con,
        filename=doc_name,
        checksum=checksum,
        document_type=profile.document_type,
        year=profile.year,
        page_count=page_count,
        upload_timestamp=datetime.now(timezone.utc),
    )
    n = load.insert_rendiconto(con, doc_id, profile.year, items)
    con.close()
    print(f"    loaded document id={doc_id}: {n} rendiconto rows")
    return True


def ingest_pdf(pdf_path: Path) -> bool:
    """Run the full pipeline for one PDF. Returns True if newly imported."""
    doc_name = pdf_path.name
    if doc_name in RENDICONTO_PROFILES:
        return ingest_rendiconto(pdf_path)
    profile = PROFILES.get(doc_name)
    if profile is None:
        print(f"  ! no layout profile registered for {doc_name} -- skipping")
        print("    (add one to src/utils/config.PROFILES)")
        return False

    print(f"==> {doc_name}")
    checksum = _checksum(pdf_path)
    print(f"    type={profile.document_type} year={profile.year} sha256={checksum[:12]}...")

    con = connect()
    init_schema(con)

    existing = load.document_exists(con, checksum)
    if existing is not None:
        print(f"    already imported (document id={existing}) -- skipping")
        con.close()
        return False

    # Extract + normalize all sections, plus the consolidation-area entities.
    sections: list[ExtractedSection] = []
    all_rows: list[NormalizedRow] = []
    entities: list[Entity] = []
    entity_metrics: list[EntityMetric] = []
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for sec_cfg in profile.sections:
            sec = extract_section(pdf, sec_cfg)
            sections.append(sec)
            all_rows.extend(normalize_section(sec))
        if profile.entity_pages:
            entities = normalize_entities(
                extract_entity_rows(pdf, profile.entity_pages)
            )
        paired = profile.entity_table_layout == "paired"
        if profile.personnel_pages:
            rows = extract_entity_rows(pdf, profile.personnel_pages)
            entity_metrics += (
                normalize_personnel_paired(rows) if paired else normalize_personnel(rows)
            )
        if profile.valuation_pages:
            rows = extract_entity_rows(pdf, profile.valuation_pages)
            entity_metrics += (
                normalize_valuation_paired(rows, profile.valuation_indirect_pages)
                if paired
                else normalize_valuation(rows)
            )
        note_items: list[NoteItem] = []
        if profile.note_pages:
            note_items = normalize_note_tables(
                extract_note_tables(pdf, profile.note_pages)
            )

    save_raw(doc_name, sections)
    _save_normalized(doc_name, all_rows)
    if entities:
        _save_entities(doc_name, entities)
    if entity_metrics:
        _save_entity_metrics(doc_name, entity_metrics)
    if note_items:
        _save_note_items(doc_name, note_items)
    metric_rows = [r for r in all_rows if r.is_metric]
    print(f"    extracted {sum(len(s.rows) for s in sections)} raw rows -> "
          f"{len(all_rows)} normalized ({len(metric_rows)} metrics); "
          f"{len(entities)} entities; {len(entity_metrics)} entity-metrics; "
          f"{len(note_items)} note-items")

    # Validate.
    checks = (
        validate.validate(all_rows, profile.year)
        + validate.validate_statement_subtotals(all_rows)
        + validate.validate_gestione_totals(all_rows)
        + validate.validate_note_items(note_items)
    )
    report_path = validate.save_report(NORMALIZED / doc_name, checks)
    for c in checks:
        print(f"    [{'OK ' if c.passed else 'FAIL'}] {c.name}: {c.detail}")
    if not all(c.passed for c in checks):
        print(f"    validation FAILED -- see {report_path}; not loading into DuckDB")
        con.close()
        return False

    # Load.
    doc_id = load.insert_document(
        con,
        filename=doc_name,
        checksum=checksum,
        document_type=profile.document_type,
        year=profile.year,
        page_count=page_count,
        upload_timestamp=datetime.now(timezone.utc),
    )
    n_tables = load.insert_tables(con, doc_id, sections)
    n_metrics = load.insert_metrics(con, doc_id, profile.year, all_rows)
    n_entities = load.insert_entities(con, doc_id, profile.year, entities)
    n_em = load.insert_entity_metrics(con, doc_id, profile.year, entity_metrics)
    n_ni = load.insert_note_items(con, doc_id, profile.year, note_items)

    # Export the entity-name crosswalk (the normalization map) as a CSV artifact.
    if entities or entity_metrics:
        cross = con.sql(
            "SELECT raw_name, source, canonical_slug, canonical_name "
            "FROM entity_crosswalk ORDER BY canonical_slug, source, raw_name"
        ).df()
        cross.to_csv(NORMALIZED / doc_name / "entity_crosswalk.csv", index=False)

    con.close()
    print(f"    loaded document id={doc_id}: {n_tables} tables, "
          f"{n_metrics} metric rows, {n_entities} entities, "
          f"{n_em} entity-metrics, {n_ni} note-items")
    return True


def main(argv: list[str]) -> int:
    if argv:
        arg = argv[0]
        pdf_path = Path(arg)
        if not pdf_path.exists():
            pdf_path = UPLOADS / arg
        targets = [pdf_path]
    else:
        targets = sorted(UPLOADS.glob("*.pdf"))

    if not targets:
        print("no PDFs to ingest")
        return 1

    for pdf_path in targets:
        if not pdf_path.exists():
            print(f"  ! not found: {pdf_path}")
            continue
        ingest_pdf(pdf_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
