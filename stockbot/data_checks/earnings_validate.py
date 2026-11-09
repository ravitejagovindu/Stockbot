"""stockbot/data_checks/earnings_validate.py — Step 12: cross-source concordance (results broadcast date vs board-meeting date) and a sample listing for external checks. Read-only."""
import sqlite3, sys
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[2]


def main():
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").strip().partition(chr(10))[0])
    ap.add_argument("symbols", nargs="*", help="query symbols to list for external checking")
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{ROOT / 'finsight.db'}?mode=ro", uri=True, timeout=120)
    f = pd.read_sql("select query_symbol, to_date, substr(broadcast_ts,1,10) bc, consolidated from earnings_results_filing where broadcast_ts is not null and period='Quarterly'", con)
    b = pd.read_sql("select query_symbol, bm_date, substr(intimation_ts,1,10) it from earnings_board_meeting where is_results_meeting=1", con)
    f["bc"] = pd.to_datetime(f.bc); b["bm_date"] = pd.to_datetime(b.bm_date); b["it"] = pd.to_datetime(b.it)
    f = f.drop_duplicates(["query_symbol", "to_date", "bc"])
    grp = {k: g.bm_date.values for k, g in b.groupby("query_symbol")}
    import numpy as np
    def nearest(r):
        a = grp.get(r.query_symbol)
        if a is None or len(a) == 0: return np.nan
        d = (a - np.datetime64(r.bc)).astype("timedelta64[D]").astype(int)
        return d[np.argmin(np.abs(d))]
    f["gap_days"] = f.apply(nearest, axis=1)
    has = f.gap_days.notna()
    print("filings with broadcast:", len(f), " with any results meeting for the symbol:", int(has.sum()))
    g = f[has].gap_days
    print("meeting date minus broadcast date, days: share |gap|<=1:", round((g.abs() <= 1).mean() * 100, 1), " <=3:", round((g.abs() <= 3).mean() * 100, 1), " >7:", round((g.abs() > 7).mean() * 100, 1))
    f["yr"] = f.bc.dt.year
    print(f[has].groupby("yr").gap_days.apply(lambda s: round((s.abs() <= 3).mean() * 100, 1)).to_string())
    # intimation lead time
    b["lead"] = (b.bm_date - b.it).dt.days
    print("intimation lead (days) quantiles, results meetings:", b.lead.quantile([.01, .05, .5, .95]).to_dict(), " share lead<0:", round((b.lead < 0).mean() * 100, 2), " share lead>=7:", round((b.lead >= 7).mean() * 100, 1))
    b["yr"] = b.bm_date.dt.year
    print(b.groupby("yr").lead.apply(lambda s: round((s >= 7).mean() * 100, 1)).to_string())
    for s in args.symbols:
        print("\n==", s)
        print(pd.read_sql("select to_date, substr(broadcast_ts,1,16) broadcast, consolidated from earnings_results_filing where query_symbol=? and period='Quarterly' and broadcast_ts is not null order by to_date desc limit 6", con, params=(s,)).to_string(index=False))
        print(pd.read_sql("select bm_date, substr(intimation_ts,1,10) intimated, purpose from earnings_board_meeting where query_symbol=? and is_results_meeting=1 order by bm_date desc limit 4", con, params=(s,)).to_string(index=False))


if __name__ == "__main__":
    main()
