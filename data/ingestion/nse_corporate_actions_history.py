"""data/ingestion/nse_corporate_actions_history.py — F2: corporate-action history from the NSE API (2010 -> today).

Source: ``https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol=X&from_date=..&to_date=..``
(public JSON, needs a browser-like session; free-text ``subject`` field).  Limits (documented): keyed by the CURRENT
symbol, so actions before a rename may be missing (see the symbol-map report); subjects are free text, so the parser is
conservative — anything it cannot read as a split/bonus ratio is stored as ``OTHER`` with the raw subject and listed in
the unresolved report instead of being guessed.

Two modes:
  --dump CSV   fetch every symbol and write the raw rows (audit artifact; no database access)
  --load CSV   insert parsed rows into corporate_actions_log (append-only: INSERT OR IGNORE, never UPDATE/DELETE)

Ratio convention (matches engine_core.adjustments):
  SPLIT  num/den = new_face_value / old_face_value   (Rs10 -> Rs2  => 2/10 = factor 0.2)
  BONUS  num:den = bonus shares : held shares        ("Bonus 4:1" => num 4, den 1 => factor 1/5)
  RIGHTS num:den = new shares : held shares (price in notes); DEMERGER / MERGER / OTHER carry no ratio.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "NSE corporates-corporateActions API"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions",
}
_NUM = r"([\d]+(?:\.[\d]+)?)"
_RS = r"(?:rs\.?|re\.?|inr)?\s*"
_SPLIT = re.compile(r"(?:split|sub-?\s*division)[^\d]*?(?:from\s*)?" + _RS + _NUM + r"[^\d]*?to\s*(?:face\s*value\s*)?" + _RS + _NUM, re.I)
_NOT_SHARES = re.compile(r"debenture|preference|preferance|ncrps|ncps|redeemable|non-?\s*convertible", re.I)  # bonus debentures/preference shares do not move the price
_BONUS = re.compile(r"bonus[^\d]{0,12}" + _NUM + r"\s*:\s*" + _NUM, re.I)
_RIGHTS = re.compile(r"rights[^\d]{0,12}" + _NUM + r"\s*:\s*" + _NUM, re.I)
_DIV = re.compile(r"dividend|\bdiv\b", re.I)


def parse_subject(subject: str) -> list[dict]:
    """Parse a free-text NSE subject into 0..n action dicts (action_type, num, den, note)."""
    s = (subject or "").strip()
    out: list[dict] = []
    if _NOT_SHARES.search(s) and re.search(r"bonus|arrangement", s, re.I):
        # bonus of debentures / (redeemable) preference shares (NCRPS) under a scheme: no effect on the equity price
        return [{"action_type": "OTHER", "num": None, "den": None, "note": "NON_PRICE: " + s}]
    for m in _SPLIT.finditer(s):
        old_fv, new_fv = float(m.group(1)), float(m.group(2))
        if old_fv > 0 and new_fv > 0 and new_fv != old_fv:
            out.append({"action_type": "SPLIT", "num": new_fv, "den": old_fv, "note": s})
    for m in ([] if _NOT_SHARES.search(s) else _BONUS.finditer(s)):
        n, d = float(m.group(1)), float(m.group(2))
        if n > 0 and d > 0:
            out.append({"action_type": "BONUS", "num": n, "den": d, "note": s})
    for m in _RIGHTS.finditer(s):
        n, d = float(m.group(1)), float(m.group(2))
        if n > 0 and d > 0:
            out.append({"action_type": "RIGHTS", "num": n, "den": d, "note": s})
    low = s.lower()
    if "demerger" in low:
        out.append({"action_type": "DEMERGER", "num": None, "den": None, "note": s})
    if re.search(r"amalgamation|merger|scheme of arrangement|arrangement", low) and "demerger" not in low:
        out.append({"action_type": "MERGER", "num": None, "den": None, "note": s})
    if not out and _DIV.search(s):
        out.append({"action_type": "DIVIDEND", "num": None, "den": None, "note": s})
    if not out and re.search(r"split|sub-?division|bonus|rights", low):  # incl. bonus debentures: no price effect
        out.append({"action_type": "OTHER", "num": None, "den": None, "note": "UNPARSED: " + s})
    if not out and re.search(r"buy\s*-?\s*back", low):
        out.append({"action_type": "OTHER", "num": None, "den": None, "note": s})
    return out


def _parse_ex(v: str) -> Optional[date]:
    try:
        return datetime.strptime(str(v).strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


class NseSession:
    def __init__(self, sleep: float = 0.6):
        self.sleep, self.n = sleep, 0
        self._new()

    def _new(self):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        try:
            self.s.get("https://www.nseindia.com", timeout=20)  # cookie warm-up (403 body is fine)
        except requests.RequestException:
            pass

    def actions(self, symbol: str, from_date: str = "01-01-2010", to_date: Optional[str] = None) -> Optional[list]:
        to_date = to_date or date.today().strftime("%d-%m-%Y")
        u = ("https://www.nseindia.com/api/corporates-corporateActions?index=equities"
             f"&symbol={requests.utils.quote(symbol)}&from_date={from_date}&to_date={to_date}")
        for attempt in range(4):
            self.n += 1
            if self.n % 150 == 0:
                self._new()
            try:
                r = self.s.get(u, timeout=30)
                if r.status_code == 200:
                    time.sleep(self.sleep)
                    return r.json()
                if r.status_code in (401, 403):
                    self._new()
            except (requests.RequestException, ValueError):
                pass
            time.sleep(2 * (attempt + 1))
        return None


def dump(symbols: list[str], out_csv: Path, sleep: float) -> None:
    done = set()
    rows: list[dict] = []
    if out_csv.exists():
        prev = pd.read_csv(out_csv)
        rows = prev.to_dict("records")
        done = set(prev["query_symbol"].unique()) | set(
            pd.read_csv(str(out_csv) + ".done.csv")["query_symbol"]) if Path(str(out_csv) + ".done.csv").exists() else set(prev["query_symbol"])
    donelog = Path(str(out_csv) + ".done.csv")
    fails = []
    ns = NseSession(sleep)
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        if sym in done:
            continue
        res = ns.actions(sym)
        if res is None:
            fails.append(sym)
            continue
        for r in res:
            rows.append({"query_symbol": sym, "symbol": r.get("symbol"), "isin": r.get("isin"), "exDate": r.get("exDate"),
                         "subject": r.get("subject"), "series": r.get("series"), "faceVal": r.get("faceVal"),
                         "recDate": r.get("recDate"), "comp": r.get("comp")})
        with open(donelog, "a", encoding="utf-8") as f:
            if donelog.stat().st_size == 0 if donelog.exists() else True:
                f.write("query_symbol\n")
            f.write(sym + "\n")
        if i % 50 == 0:
            pd.DataFrame(rows).to_csv(out_csv, index=False)
            print(f"{i}/{len(symbols)} symbols, {len(rows)} rows, {time.time() - t0:.0f}s, fails={len(fails)}", flush=True)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    pd.DataFrame({"query_symbol": fails}).to_csv(str(out_csv) + ".failed.csv", index=False)
    print(f"DONE rows={len(rows)} failed={len(fails)}", flush=True)


def load(csv_path: Path, db_path: str) -> dict:
    """Append parsed actions to corporate_actions_log (INSERT OR IGNORE; never updates or deletes)."""
    raw = pd.read_csv(csv_path)
    loaded_at = datetime.now().isoformat(timespec="seconds")
    recs, unresolved = [], []
    for r in raw.itertuples():
        ex = _parse_ex(r.exDate)
        sym = str(r.symbol or r.query_symbol).strip()
        if ex is None:
            unresolved.append((sym, r.exDate, r.subject, "bad ex-date"))
            continue
        for a in parse_subject(str(r.subject)):
            if a["action_type"] == "OTHER" and str(a["note"]).startswith("UNPARSED"):
                unresolved.append((sym, r.exDate, r.subject, "unparsed ratio"))
            recs.append((sym, ex.isoformat(), a["action_type"], a["num"], a["den"], a["note"][:500], SOURCE, loaded_at))
    con = sqlite3.connect(db_path, timeout=60)
    before = con.execute("select count(*) from corporate_actions_log").fetchone()[0]
    with con:
        con.executemany(
            "INSERT OR IGNORE INTO corporate_actions_log "
            "(symbol, ex_date, action_type, ratio_numerator, ratio_denominator, notes, source, loaded_at) "
            "VALUES (?,?,?,?,?,?,?,?)", recs)
    after = con.execute("select count(*) from corporate_actions_log").fetchone()[0]
    con.close()
    return {"parsed_rows": len(recs), "inserted": after - before, "unresolved": unresolved}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", help="write raw rows to this CSV")
    ap.add_argument("--symbols-file", help="text file with one symbol per line")
    ap.add_argument("--load", help="raw CSV to load into corporate_actions_log")
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--sleep", type=float, default=0.6)
    a = ap.parse_args()
    if a.dump:
        syms = [x.strip() for x in Path(a.symbols_file).read_text().splitlines() if x.strip()]
        dump(syms, Path(a.dump), a.sleep)
    elif a.load:
        res = load(Path(a.load), a.db)
        print({k: (v if k != "unresolved" else len(v)) for k, v in res.items()})
    else:
        ap.error("--dump or --load required")


if __name__ == "__main__":
    sys.exit(main())
