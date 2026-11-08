"""Yahoo fallback for the dates the NSE index file does not cover (see f2_index_gap_fill.py); source labelled 'yahoo:<ticker>'.
Also cross-checks Yahoo closes against the NSE-file rows already fetched (agreement report)."""
from __future__ import annotations
import sqlite3, sys
import yfinance as yf

T = {"NIFTY50_INDEX": "^NSEI", "INDIA_VIX": "^INDIAVIX"}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").strip().partition(chr(10))[0])
    args = ap.parse_args()
    from stockbot.data.ingestion.f2_index_gap_fill import missing
    con = sqlite3.connect("finsight.db", timeout=60)
    miss = missing(con)
    have = {(s, d) for s, d in con.execute("select symbol, trade_date from index_gap_fill")}
    for sym, tk in T.items():
        todo = [d for d in miss[sym] if (sym, d) not in have]
        df = yf.download(tk, start="2014-01-01", end="2026-12-31", progress=False, auto_adjust=False)
        df.columns = [c[0] for c in df.columns]
        df.index = df.index.strftime("%Y-%m-%d")
        for d in todo:
            if d in df.index:
                r = df.loc[d]
                con.execute("insert or replace into index_gap_fill values (?,?,?,?,?,?,?)",
                            (sym, d, float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]), f"yahoo:{tk}"))
            else:
                print("NOT FOUND", sym, d)
        # agreement with NSE-file rows
        diffs = []
        for d, c in con.execute("select trade_date, close_raw from index_gap_fill where symbol=? and source like 'https://%'", (sym,)):
            if d in df.index:
                diffs.append(abs(float(df.loc[d]["Close"]) / c - 1))
        if diffs:
            print(sym, "Yahoo vs NSE-file close on", len(diffs), "overlapping fetched dates: max rel diff", round(max(diffs), 5))
    con.commit()
    print(con.execute("select symbol, substr(source,1,5), count(*) from index_gap_fill group by 1,2").fetchall())
    return 0


if __name__ == "__main__":
    sys.exit(main())
