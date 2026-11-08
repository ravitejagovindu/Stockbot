"""scripts/provenance/f2_pre2020_compare.py — reviewer condition 3.1: compare the lake's pre-2020 rows with staging (2013-2019).

Read-only.  Aggregates inside SQLite (memory-safe).  Writes docs/data_audit/pre2020_lake_vs_staging.csv and
pre2020_symbol_coverage.csv and prints a summary.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "data_audit"
IDX = ("NIFTY50_INDEX", "INDIA_VIX")


def main(db: str = str(ROOT / "finsight.db")) -> None:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    by_year = pd.read_sql("""
        select substr(s.trade_date,1,4) year,
               count(*) n_matched,
               avg(case when abs(m.close_raw / s.close_raw - 1) < 0.001 then 1.0 else 0.0 end) close_within_0_1pct,
               avg(case when abs(m.close_raw / s.close_raw - 1) < 0.02 then 1.0 else 0.0 end) close_within_2pct,
               avg(case when m.volume_raw = s.volume_raw then 1.0 else 0.0 end) volume_equal,
               sum(case when abs(m.close_raw / s.close_raw - 1) >= 0.02 then 1 else 0 end) n_close_mismatch_2pct
        from market_data_lake_staging s
        join market_data_lake m on m.symbol = s.symbol and m.trade_date = s.trade_date
        where s.trade_date < '2020-01-01'
        group by 1 order by 1""", con)
    cnt = pd.read_sql("""
        select y.year, s_n staging_rows, coalesce(l_n,0) lake_rows from (
           select substr(trade_date,1,4) year, count(*) s_n from market_data_lake_staging where trade_date < '2020-01-01' group by 1) y
        left join (select substr(trade_date,1,4) year, count(*) l_n from market_data_lake
                   where trade_date < '2020-01-01' and symbol not in ('NIFTY50_INDEX','INDIA_VIX') group by 1) l on l.year = y.year""", con)
    res = cnt.merge(by_year, on="year", how="left")
    res.to_csv(OUT / "pre2020_lake_vs_staging.csv", index=False)

    # symbols: in lake pre-2020 / in staging pre-2020 / only in staging (delisted names to be inserted)
    lake_syms = {r[0] for r in con.execute(
        "select distinct symbol from market_data_lake where trade_date < '2020-01-01' and symbol not in ('NIFTY50_INDEX','INDIA_VIX')")}
    all_lake = {r[0] for r in con.execute("select distinct symbol from market_data_lake where symbol not in ('NIFTY50_INDEX','INDIA_VIX')")}
    stg = pd.read_sql("select symbol, count(*) n_days, min(trade_date) first_date, max(trade_date) last_date "
                      "from market_data_lake_staging where trade_date < '2020-01-01' group by symbol", con)
    stg["in_lake_pre2020"] = stg["symbol"].isin(lake_syms)
    stg["in_lake_any"] = stg["symbol"].isin(all_lake)
    stg.to_csv(OUT / "pre2020_symbol_coverage.csv", index=False)
    only = stg[~stg["in_lake_any"]]
    print(res.to_string(index=False))
    print(f"\nstaging symbols with pre-2020 data: {len(stg)}; in lake pre-2020: {int(stg['in_lake_pre2020'].sum())}; "
          f"absent from the lake entirely (delisted names to insert): {len(only)} "
          f"({int(only['n_days'].sum())} rows)")
    print(f"in lake any date but no pre-2020 rows in lake: {int((stg['in_lake_any'] & ~stg['in_lake_pre2020']).sum())}")


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
