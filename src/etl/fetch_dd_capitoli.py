"""Fetch every determinazione dirigenziale (DD) PDF referenced by
``contratti_pubatti_base.csv`` and extract its impegni di spesa (capitoli).

For each DD-with-CIG (2023-2025) harvested from pubatti.comune.torino.it:
download the primary PDF (public ``recuperaFile`` on the ``/invoke`` servlet,
cached under ``uploads/determinazioni_pubatti/pdfs/<idUd>.pdf``), read the
imputazione grid with pdfplumber.extract_tables() (text-regex fallback for
un-ruled tables), and SNAP the -- often space-broken or truncated -- capitolo
digits to the authoritative 12-digit ``rendiconto_capitoli`` codes. Rows whose
digits cannot be snapped to a *spesa* capitolo (entrata / contropartita) are
dropped; missione/programma/macroaggregato come from the DB, not from the PDF.

Output (appended, resume-safe via the sidecar ``_processed_ids.txt``):
    uploads/determinazioni_pubatti/determinazioni_capitoli_all.csv
        anno;dd_numero;idUd;capitolo;anno_imp;importo;missione;missione_nome;
        programma;macro;denominazione;match
A human-readable progress snapshot is rewritten every 25 DD in
``uploads/determinazioni_pubatti/_DOWNLOAD_PROGRESS.txt``.

Usage:
    python -m src.etl.fetch_dd_capitoli            # process (or resume) all
    python -m src.etl.fetch_dd_capitoli --status   # just print progress
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import duckdb
import pdfplumber

from src.utils.config import UPLOADS
from src.database.schema import DB_PATH

csv.field_size_limit(10 ** 7)

SRC = UPLOADS / "determinazioni_pubatti"
BASE = SRC / "contratti_pubatti_base.csv"
OUT = SRC / "determinazioni_capitoli_all.csv"
DONE = SRC / "_processed_ids.txt"
PROGRESS = SRC / "_DOWNLOAD_PROGRESS.txt"
PDF_CACHE = SRC / "pdfs"

URL = "https://pubatti.comune.torino.it/coto/dispatcher/alboPretorioServlet/invoke"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149 Safari/537.36")

OUT_COLS = ["anno", "dd_numero", "idUd", "capitolo", "anno_imp", "importo",
            "missione", "missione_nome", "programma", "macro", "denominazione", "match"]

MONEY = re.compile(r'(\d{1,3}(?:\.\d{3})*,\d{2})')
CAP = re.compile(r'(\d{9,12})')
YEAR = re.compile(r'\b(20\d{2})\b')
DATE = r'\d{2}[/.]\d{2}[/.]\d{2,4}'
ANCHOR = re.compile(rf'(\d[\d ]{{7,13}}\d)\s+\d{{1,3}}\s+(?:{DATE})')


# ---------------------------------------------------------------- pubatti I/O

def _post(params: dict, raw: bool = False, retries: int = 3):
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                b = r.read()
            return b if raw else json.loads(b.decode("utf-8"))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def fetch_pdf(idud: str, idpub: str):
    """Return the cached path of the DD's primary PDF, downloading if needed."""
    cache = PDF_CACHE / f"{idud}.pdf"
    if cache.exists() and cache.stat().st_size > 1000:
        return cache
    det = _post({"dataInputXml":
                 f'<?xml version="1.0" encoding="UTF-8" ?><idUd>{idud}</idUd>'
                 f'<idPubblicazione>{idpub}</idPubblicazione>',
                 "nameService": "getDettaglio"})
    fs = det.get("filesAlbo", [])
    prim = next((f for f in fs if f.get("flgPrimario") == "1"), fs[0] if fs else None)
    if not prim:
        return None
    xml = (f'<?xml version="1.0" encoding="UTF-8" ?><uriFile>{prim["uriFile"]}</uriFile>'
           f'<flgConvertibile></flgConvertibile><mimetype></mimetype><nomeFile></nomeFile>'
           f'<flgFirmato></flgFirmato><impronta>{urllib.parse.quote(prim["impronta"])}</impronta>'
           f'<algoritmo>{prim["algoritmoImpronta"]}</algoritmo>'
           f'<encoding>{prim["encodingImpronta"]}</encoding>')
    pdf = _post({"dataInputXml": xml, "nameService": "recuperaFile"}, raw=True)
    cache.write_bytes(pdf)
    return cache


# ------------------------------------------------------------- capitolo snap

def load_capitoli(db_path=DB_PATH):
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        """SELECT DISTINCT capitolo_code, liv1_code, liv1_name, liv2_code,
                  liv3_code, denominazione
           FROM rendiconto_capitoli WHERE kind='spesa'""").fetchall()
    con.close()
    exact, base9 = {}, {}
    for c, m, mn, p, ma, den in rows:
        exact[c] = dict(capitolo=c, missione=m, missione_nome=mn,
                        programma=p, macro=ma, denominazione=den)
        base9.setdefault(c[:9], []).append(c)
    return exact, base9


def snap(digits: str, exact: dict, base9: dict):
    d = re.sub(r'\D', '', digits or '')
    if d in exact:
        return exact[d], 'exact'
    cands = base9.get(d[:9], [])
    if len(cands) == 1:
        return exact[cands[0]], 'base9-unique'
    if cands:
        best = max(cands, key=lambda c: len(os.path.commonprefix([c, d])))
        return exact[best], 'base9-multi'
    return None, 'unmatched'


# ---------------------------------------------------------------- extraction

def _norm(s):
    return re.sub(r'\s+', ' ', (s or '')).strip()


def _rows_from_tables(pdf):
    out = []
    for pg in pdf.pages:
        for tb in (pg.extract_tables() or []):
            if not tb or len(tb) < 2:
                continue
            hi = next((i for i, row in enumerate(tb[:3])
                       if 'capitolo' in " ".join(_norm(c) for c in row).lower()
                       and any(k in " ".join(_norm(c) for c in row).lower()
                               for k in ('importo', 'miss'))), None)
            if hi is None:
                continue
            cm = {}
            for i, c in enumerate(tb[hi]):
                t = _norm(c).lower().replace(' ', '')
                if 'importo' in t:
                    cm['importo'] = i
                elif 'capitolo' in t:
                    cm['capitolo'] = i
                elif ('anno' in t or 'bilancio' in t):
                    cm.setdefault('anno', i)
            if 'capitolo' not in cm:
                continue
            for row in tb[hi + 1:]:
                if cm['capitolo'] >= len(row):
                    continue
                mcap = CAP.search(_norm(row[cm['capitolo']]).replace(' ', ''))
                if not mcap:
                    continue
                imp = _norm(row[cm['importo']]) if cm.get('importo') is not None \
                    and cm['importo'] < len(row) else ''
                ann = _norm(row[cm['anno']]) if cm.get('anno') is not None \
                    and cm['anno'] < len(row) else ''
                m_money, m_year = MONEY.search(imp), YEAR.search(ann)
                out.append(dict(digits=mcap.group(1),
                                importo=m_money.group(1) if m_money else None,
                                anno=m_year.group(1) if m_year else None))
    return out


def _rows_from_text(pdf):
    text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    lines = text.split("\n")
    out = []
    for idx, line in enumerate(lines):
        for m in ANCHOR.finditer(line):
            above = "\n".join(lines[max(0, idx - 2):idx + 1])
            mon = MONEY.findall(line[:m.start()]) or MONEY.findall(above)
            yr = YEAR.search(above)
            out.append(dict(digits=re.sub(r'\D', '', m.group(1)),
                            importo=mon[0] if mon else None,
                            anno=yr.group(1) if yr else None))
    return out


def extract(fp, exact, base9):
    """All snapped impegni of one DD PDF: [{capitolo, missione, ..., importo, anno}]."""
    with pdfplumber.open(fp) as pdf:
        raw = _rows_from_tables(pdf) or _rows_from_text(pdf)
    seen, imput = set(), []
    for r in raw:
        info, how = snap(r['digits'], exact, base9)
        if not info:
            continue
        key = (info['capitolo'], r['anno'], r['importo'])
        if key in seen:
            continue
        seen.add(key)
        imput.append({**info, 'importo': r['importo'], 'anno': r['anno'], 'match': how})
    return imput


# ----------------------------------------------------------------- main loop

def _write_progress(done, total, withcap, err, t0):
    rate = done / max(time.time() - t0, 1) * 60
    todo = total - done
    eta = f"{int(todo / rate)} min" if rate > 0 else "?"
    PROGRESS.write_text(
        f"STATO ESTRAZIONE CAPITOLI  —  {time.strftime('%H:%M:%S')}\n"
        f"================================================\n"
        f"DD processate : {done} / {total}  ({100 * done // max(total, 1)}%)\n"
        f"con capitoli  : {withcap}\n"
        f"errori        : {err}\n"
        f"ritmo         : ~{rate:.0f} DD/min   ETA ~{eta}\n")


def main(argv: list[str]) -> int:
    if not BASE.exists():
        print(f"manca {BASE}")
        return 1

    with open(BASE, newline="", encoding="utf-8") as f:
        base = list(csv.DictReader(f, delimiter=";"))
    seen_ud, dds = set(), []
    for r in base:
        if r["idUd"] not in seen_ud:
            seen_ud.add(r["idUd"])
            dds.append(r)

    processed = set(DONE.read_text().split()) if DONE.exists() else set()
    todo = [r for r in dds if r["idUd"] not in processed]

    if "--status" in argv:
        print(f"DD totali {len(dds)} | processate {len(processed)} | da fare {len(todo)}")
        return 0

    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    exact, base9 = load_capitoli()
    print(f"DD totali: {len(dds)} | già processate: {len(processed)} | da fare: {len(todo)}",
          flush=True)

    new_out = not OUT.exists()
    out_f = open(OUT, "a", newline="", encoding="utf-8")
    w = csv.writer(out_f, delimiter=";")
    if new_out:
        w.writerow(OUT_COLS)
    done_f = open(DONE, "a", encoding="utf-8")

    done = err = withcap = 0
    t0 = time.time()
    for r in todo:
        # a failed DD is NOT marked processed: the next run retries it
        try:
            fp = fetch_pdf(r["idUd"], r["idPubblicazione"])
            imp = extract(fp, exact, base9) if fp else []
        except Exception:
            err += 1
            done += 1
            continue
        if imp:
            withcap += 1
        for i in imp:
            w.writerow([r["anno"], r["dd_numero"], r["idUd"], i["capitolo"],
                        i["anno"], i["importo"], i["missione"], i["missione_nome"],
                        i["programma"], i["macro"], i["denominazione"], i["match"]])
        done_f.write(r["idUd"] + "\n")
        done += 1
        if done % 25 == 0:
            out_f.flush()
            done_f.flush()
            _write_progress(len(processed) + done, len(dds), withcap, err, t0)
            print(f"  {done}/{len(todo)} (con capitoli {withcap}, err {err})", flush=True)

    out_f.close()
    done_f.close()
    _write_progress(len(processed) + done, len(dds), withcap, err, t0)
    print(f"\nFATTO. processate ora: {done} | con capitoli: {withcap} | err: {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
