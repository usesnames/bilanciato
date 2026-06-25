"""Parse a Comune di Torino *determinazione dirigenziale* (DD) PDF and extract the
fields that bridge a contract to the budget: oggetto, CIG(s), importo, and — most
importantly — the **capitoli di spesa** impegnati (code + name + year + amount).

The DDs are heterogeneous: the "dettaglio economico-finanziario" table has a
different column order across divisions, labels vary, some DDs carry no CIG
(diritto esclusivo) or several, and a few are image-only scans (no text). The
parser is therefore best-effort and explicit about what it could and could not
find; the capitolo *name* (from the «Descrizione capitolo …» line) is the most
reliable output, the numeric *code* is extracted when the value row is legible.

Usage:
    python -m src.etl.parse_dd path/to/DD.pdf [more.pdf ...]
    python -m src.etl.parse_dd --json path/to/DD.pdf      # machine-readable

The intended workflow: download a bando's DD from bandi.comune.torino.it, run
this on it, and use the (CIG, capitolo_code) pairs to populate the bridge.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict

import pdfplumber

# A capitolo code in the rendiconto is a 9-12 digit run; the year and the date
# must not be mistaken for it.
_YEAR = re.compile(r"\b(20\d{2})\b")
_MONEY = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")
_CAP_CODE = re.compile(r"\b(\d{9,12})\b")
_CIG = re.compile(r"C\.?\s?I\.?\s?G\.?\s*[:.]?\s*([0-9A-Z]{10})\b")
_DESCR = re.compile(r"Descrizione\s+[Cc]apitolo\s*(?:e\s*(?:articolo)?)?", re.I)
_TABLE_HDR = re.compile(r"[Ii]mporto\s+[Aa]nno", re.I)
_STOP_DESCR = re.compile(r"Conto\s+Finanziario|[Ii]mporto\s+[Aa]nno|^\s*$", re.I)


@dataclass
class Imputazione:
    capitolo_code: str | None
    capitolo_nome: str | None
    anno: int | None
    importo: str | None


@dataclass
class DDResult:
    file: str
    is_scanned: bool = False
    oggetto: str | None = None
    cig: list[str] = field(default_factory=list)
    importo: str | None = None
    imputazioni: list[Imputazione] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _full_text(path: str) -> tuple[str, int]:
    text_parts, n = [], 0
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        for pg in pdf.pages:
            text_parts.append(pg.extract_text() or "")
    return "\n".join(text_parts), n


def _money_to_str(blob: str) -> str | None:
    """Recover an Italian amount from a (possibly wrapped) blob like '6.895,0 0'."""
    m = _MONEY.search(blob.replace(" ", "").replace("\n", ""))
    return m.group(0) if m else None


def _extract_oggetto(text: str) -> str | None:
    m = re.search(r"OGGETTO\s*:\s*(.+)", text)
    if not m:
        return None
    # the oggetto often wraps onto the next line(s) in capitals; take up to ~240 chars
    start = m.start(1)
    chunk = text[start:start + 400].split("\n")
    out = [chunk[0].strip()]
    for ln in chunk[1:4]:
        s = ln.strip()
        if s and (s.isupper() or s[0].isupper()) and "OGGETTO" not in s:
            out.append(s)
        else:
            break
    return re.sub(r"\s+", " ", " ".join(out)).strip()[:300]


def _extract_importo(text: str) -> str | None:
    head = text[:4000]
    cands = []
    for pat in (r"IMPEGNO DI SPESA[^\d]{0,20}([\d.]+,\d{2})",
                r"PRESUNTA[^\d]{0,12}EURO\s*([\d.]+,\d{2})",
                r"base di gara[^\d]{0,40}([\d.]+,\d{2})",
                r"EURO\s*([\d.]+,\d{2})"):
        for m in re.finditer(pat, head, re.I):
            cands.append(m.group(1))
    if not cands:
        return None
    # the headline figure is the largest among the candidates
    return max(cands, key=lambda s: float(s.replace(".", "").replace(",", ".")))


def _capitolo_name(lines: list[str], i: int) -> str | None:
    """Collect the capitolo name starting at the «Descrizione capitolo» line i."""
    first = _DESCR.sub("", lines[i]).strip(" :-")
    parts = [first] if first else []
    for k in range(i + 1, min(i + 5, len(lines))):
        s = lines[k].strip()
        if not s or _STOP_DESCR.search(s) or _DESCR.search(s):
            break
        # stop if we hit a fresh value row (starts with money + year)
        if _MONEY.match(s) and _YEAR.search(s):
            break
        parts.append(s)
    name = re.sub(r"\s+", " ", " ".join(parts)).strip(" :-")
    # 'articolo' here is the table-label «Descrizione capitolo e articolo» bleeding
    # into the value; it never occurs in a real capitolo name, so drop it.
    name = re.sub(r"\b[Aa]rticolo\b", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" :-")
    return name or None


def _value_row(lines: list[str], i: int) -> tuple[str | None, int | None, str | None]:
    """Look upward from a «Descrizione capitolo» line for the value row carrying
    (capitolo_code, anno, importo). Returns the best guess."""
    window = "\n".join(lines[max(0, i - 6):i])
    flat = window.replace("\n", " ")
    anno = None
    ym = _YEAR.search(flat)
    if ym:
        anno = int(ym.group(1))
    # capitolo code: the longest 9-12 digit run that is not the year
    codes = [c for c in _CAP_CODE.findall(flat) if not (2000 <= int(c) <= 2099)]
    code = max(codes, key=len) if codes else None
    importo = _money_to_str(window)
    return code, anno, importo


def parse_dd(path: str) -> DDResult:
    text, npages = _full_text(path)
    res = DDResult(file=path)
    if len(text.strip()) < 200:
        res.is_scanned = True
        res.warnings.append(
            f"PDF senza testo estraibile ({npages} pagine): probabile scansione, "
            "serve OCR. Nessun dato estratto.")
        return res

    res.oggetto = _extract_oggetto(text)
    res.cig = list(dict.fromkeys(_CIG.findall(text)))
    res.importo = _extract_importo(text)

    lines = text.split("\n")
    seen = set()
    for i, ln in enumerate(lines):
        if not _DESCR.search(ln):
            continue
        name = _capitolo_name(lines, i)
        code, anno, importo = _value_row(lines, i)
        key = (code, name)
        if key in seen:
            continue
        seen.add(key)
        res.imputazioni.append(Imputazione(code, name, anno, importo))

    if not res.imputazioni:
        res.warnings.append("Nessun capitolo trovato (formato tabella non riconosciuto).")
    elif any(im.capitolo_code is None for im in res.imputazioni):
        res.warnings.append("Capitolo trovato per nome ma codice numerico non leggibile "
                            "(riga valori frammentata).")
    if not res.cig:
        res.warnings.append("Nessun CIG nel documento (può essere affidamento senza CIG).")
    return res


def _print(res: DDResult) -> None:
    print(f"\n=== {res.file} ===")
    if res.is_scanned:
        print("  ⚠️  " + res.warnings[0])
        return
    print(f"  OGGETTO : {res.oggetto or '?'}")
    print(f"  CIG     : {', '.join(res.cig) if res.cig else '— (nessuno)'}")
    print(f"  IMPORTO : {res.importo or '?'}")
    print(f"  CAPITOLI ({len(res.imputazioni)}):")
    for im in res.imputazioni:
        print(f"    - {im.capitolo_code or '??? '} | anno {im.anno or '?'} | "
              f"{im.importo or '?'} | {im.capitolo_nome or '?'}")
    for w in res.warnings:
        print(f"  ⚠️  {w}")


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    paths = [a for a in argv if a != "--json"]
    if not paths:
        print("uso: python -m src.etl.parse_dd [--json] <DD.pdf> [...]")
        return 1
    results = [parse_dd(p) for p in paths]
    if as_json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        for r in results:
            _print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
