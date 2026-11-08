"""scripts/provenance/f2_volume_continuity.py — are volume units continuous across the Bhavcopy legacy -> UDiFF format change?

For each symbol: median volume of the N sessions before vs after a boundary.  The real boundary (2024-06-28 | 2024-07-01)
is compared with control boundaries that have no format change; the median across symbols of after/before should be ~1
for every boundary, and the real one must not stand out.  Read-only.
"""
from __future__ import annotations
import argparse, sqlite3, sys
import pandas as pd

BOUNDARY = "2024-07-01"          # first UDiFF session
CONTROLS = ["2023-07-03", "2022-07-01", "2021-07-01", "2025-07-01"]


def ratio_stats(con, first_after: str, n: int = 20, min_vol: int = 10_000) -> dict:
    dates = [r[0] for r in con.execute("select distinct trade_date from market_data_lake_staging order by 1")]
    i = dates.index(first_after)
    b, a = dates[i - n:i], dates[i:i + n]
    q = lambda ds: pd.read_sql_query(
        f"select symbol, volume_raw v from market_data_lake_staging where trade_date between '{ds[0]}' and '{ds[-1]}' "
        f"and series='EQ'", con).groupby("symbol")["v"].median()
    mb, ma = q(b), q(a)
    r = (ma / mb)[(mb >= min_vol) & (ma > 0)].dropna()
    return {"boundary": first_after, "symbols": len(r), "median_ratio": round(float(r.median()), 3),
            "p10": round(float(r.quantile(.1)), 3), "p90": round(float(r.quantile(.9)), 3),
            "share_ratio_gt_5_or_lt_0.2": round(float(((r > 5) | (r < .2)).mean()), 4)}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--db", default="finsight.db"); a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    rows = [ratio_stats(con, d) for d in [BOUNDARY] + CONTROLS]
    df = pd.DataFrame(rows); print(df.to_string(index=False))
    df.to_csv("docs/data_audit/volume_continuity.csv", index=False)
    real = df.iloc[0]["median_ratio"]; ctl = df.iloc[1:]["median_ratio"]
    ok = 0.7 <= real <= 1.4 and abs(real - ctl.median()) < 0.25
    print("PASS" if ok else "FAIL: volume units differ across the format change")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
