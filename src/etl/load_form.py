"""Load a partecipata's statements from a hand-filled YAML *form*.

Some fascicoli are image-only scans (e.g. FCT Holding's consolidated bilancio):
no text to parse. For these, we ship a YAML form pre-filled with the civil-code
schema voci; a human reads the figures off the scan and types them in, and this
loader turns the filled form into ``entity_statements`` rows.

The form has an ``entity`` block (slug/name/source_document/years) and three
ordered lists — ``stato_patrimoniale_attivo``, ``stato_patrimoniale_passivo``,
``conto_economico`` — each item being ``{code, name, total, v2024, v2023}``.
Rows empty in both years are skipped; a "di cui ... Comune di Torino" memo line
is flagged as a rapporto col socio so the dashboard surfaces it.

Idempotent per entity (delete that entity's rows, re-insert). Validates the
quadratura: TOTALE ATTIVO == TOTALE PASSIVO for every year present.

Usage:
    python -m src.etl.load_form uploads/partecipate/fct_holding_form.yaml
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import yaml

from src.normalization import entity_statements as es
from src.utils.config import ROOT, UPLOADS

FORMS_DIR = ROOT / "forms"

_CATEGORIES = {
    "stato_patrimoniale_attivo": es.ATTIVO,
    "stato_patrimoniale_passivo": es.PASSIVO,
    "conto_economico": es.CONTO_ECONOMICO,
}


def _val(raw) -> int | None:
    """Coerce a form cell to an int (euros), tolerating '1.234.567' / '' / None."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw).strip().replace(".", "").replace(" ", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("+", "")
    return -int(s) if neg else int(s)


def parse_form(path: Path) -> tuple[dict, list[es.StatementItem]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    ent = doc["entity"]
    year, prev_year = int(ent["year"]), int(ent["prev_year"])
    items: list[es.StatementItem] = []

    for key, category in _CATEGORIES.items():
        seq = 0
        for row in doc.get(key) or []:
            name = str(row["name"]).strip()
            cur, prev = _val(row.get("v2024")), _val(row.get("v2023"))
            if cur is None and prev is None:
                continue
            rp = "socio" if "comune di torino" in name.lower() else None
            for yr, v in ((year, cur), (prev_year, prev)):
                if v is None:
                    continue
                items.append(es.StatementItem(
                    category=category, seq=seq, code=(row.get("code") or "").strip(),
                    name=name, year=yr, value=Decimal(v),
                    is_total=bool(row.get("total")), related_party=rp,
                    source_page=0))
            seq += 1
    return ent, items


def _validate(ent: dict, items: list[es.StatementItem]) -> list[str]:
    problems: list[str] = []
    for yr in {it.year for it in items}:
        def grand(needle: str) -> Decimal | None:
            return next((it.value for it in items
                         if it.year == yr and it.related_party is None
                         and it.name.replace(" ", "").upper() == needle), None)
        ta = grand("TOTALEATTIVO")
        tp = grand("TOTALEPASSIVO")
        if ta is None or tp is None:
            problems.append(f"{yr}: TOTALE ATTIVO/PASSIVO non compilato ({ta} / {tp})")
        elif ta != tp:
            problems.append(f"{yr}: ATTIVO {ta:,} != PASSIVO {tp:,} (Δ {ta - tp:,})")
    return problems


def load(path: Path) -> int:
    from src.database.schema import connect, init_schema

    ent, items = parse_form(path)
    problems = _validate(ent, items)
    for p in problems:
        print(f"    [FAIL] {p}")
    if problems:
        raise SystemExit(f"validazione fallita per {ent['slug']}; non carico")

    slug, name, src = ent["slug"], ent["name"], ent["source_document"]
    con = connect()
    init_schema(con)
    con.execute("DELETE FROM entity_statements WHERE entity_slug = ?", [slug])
    start = con.execute("SELECT COALESCE(max(id), 0) FROM entity_statements").fetchone()[0]
    rows = [
        (start + 1 + n, slug, name, it.year, it.category, it.seq,
         it.code or None, it.name, it.value, "EUR", it.is_total,
         it.related_party, src, it.source_page)
        for n, it in enumerate(items)
    ]
    con.executemany(
        """INSERT INTO entity_statements
           (id, entity_slug, entity_name, year, category, seq, code, name,
            value, unit, is_total, related_party, source_document, source_page)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    con.close()
    yrs = sorted({it.year for it in items})
    print(f"    [OK ] {slug}: {len(rows)} righe ({'+'.join(map(str, yrs))}), "
          f"quadratura verificata")
    return len(rows)


def main(argv: list[str]) -> int:
    if not argv:
        print("uso: python -m src.etl.load_form <percorso_form.yaml | slug>")
        print(f"     (form cercati in {FORMS_DIR})")
        return 1
    arg = argv[0]
    candidates = [Path(arg), FORMS_DIR / arg, FORMS_DIR / f"{arg}.yaml",
                  FORMS_DIR / f"{arg}_form.yaml", UPLOADS / "partecipate" / arg]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        print(f"form non trovato: {arg}")
        return 1
    load(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
