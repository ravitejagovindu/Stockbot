"""stockbot/data/ingestion/f2_index_gap_fill.py — fetch Nifty 50 / India VIX rows for dates the lake lacks, from NSE's daily index file
(archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv).  The file's own 'Index Date' must equal the requested
date.  Results go to table index_gap_fill (symbol, trade_date, OHLC, source) — NOT into market_data_lake (the swap does that,
labelled and append-only).  Dates the NSE file does not cover are listed so another source can be used.
"""
from __future__ import annotations
import argparse, io, sqlite3, sys, time
import pandas as pd, requests

URL = "https://archives.nseindia.com/content/indices/ind_close_all_{d}.csv"
NAMES = {"Nifty 50": "NIFTY50_INDEX", "India VIX": "INDIA_VIX"}


def missing(con) -> dict[str, list[str]]:
    stg = {r[0] for r in con.execute("select distinct trade_date from market_data_lake_staging")}
    out = {}
    for sym in NAMES.values():
        have = {r[0] for r in con.execute("select trade_date from market_data_lake where symbol=?", (sym,))}
        lo = min(have)
        out[sym] = sorted(d for d in stg if d >= lo and d not in have)
    return out


def parse(text: str, want: str) -> dict[str, tuple]:
    df = pd.read_csv(io.StringIO(text))
    res = {}
    for name, sym in NAMES.items():
        r = df[df["Index Name"].str.strip() == name]
        if r.empty:
            continue
        r = r.iloc[0]
        d = pd.to_datetime(r["Index Date"], format="%d-%m-%Y").strftime("%Y-%m-%d")
        if d != want:
            continue                                    # file for another date: reject
        res[sym] = (d, float(r["Open Index Value"]), float(r["High Index Value"]), float(r["Low Index Value"]), float(r["Closing Index Value"]))
    return res


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--db", default="finsight.db"); a = ap.parse_args()
    con = sqlite3.connect(a.db, timeout=60)
    con.execute("create table if not exists index_gap_fill(symbol text, trade_date text, open_raw real, high_raw real, low_raw real, close_raw real, source text, primary key(symbol, trade_date))")
    miss = missing(con)
    dates = sorted(set(sum(miss.values(), [])))
    h = {"User-Agent": "Mozilla/5.0"}
    not_found = {s: [] for s in NAMES.values()}
    for d in dates:
        url = URL.format(d=d[8:] + d[5:7] + d[:4])
        r = requests.get(url, headers=h, timeout=30)
        got = parse(r.text, d) if r.status_code == 200 else {}
        for sym in NAMES.values():
            if d in miss[sym]:
                if sym in got:
                    con.execute("insert or replace into index_gap_fill values (?,?,?,?,?,?,?)", (sym, *got[sym], url))
                else:
                    not_found[sym].append(d)
        time.sleep(0.3)
    con.commit()
    for s, v in not_found.items():
        print(s, "missing:", len(miss[s]), "| not covered by NSE file:", v)
    print(con.execute("select symbol, count(*) from index_gap_fill group by 1").fetchall())
    return 0


if __name__ == "__main__":
    sys.exit(main())
