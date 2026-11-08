"""scripts/provenance/f2_post_swap_checks.py — read-only post-swap report (F2 Step 3).  Writes docs/data_audit/post_swap_report_<tag>.md."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
IDX = "('NIFTY50_INDEX','INDIA_VIX')"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--tag", default="real")
    a = ap.parse_args()
    c = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=120)
    out, fails = [], []

    def sec(title, df):
        out.append(f"\n## {title}\n\n```\n{df.to_string(index=False)}\n```")

    q = lambda s, *p: pd.read_sql_query(s, c, params=p)
    # 1. rows per year: lake vs staging vs archive
    sec("Rows and trading days per year (equities; lake after swap vs staging vs Yahoo archive)", q(f"""
        select y.yr, l.rows lake_rows, l.days lake_days, l.syms lake_symbols, s.rows staging_rows, a.rows yahoo_archive_rows
        from (select distinct substr(trade_date,1,4) yr from market_data_lake) y
        left join (select substr(trade_date,1,4) yr, count(*) rows, count(distinct trade_date) days, count(distinct symbol) syms
                   from market_data_lake where symbol not in {IDX} group by 1) l using(yr)
        left join (select substr(trade_date,1,4) yr, count(*) rows from market_data_lake_staging where series='EQ' group by 1) s using(yr)
        left join (select substr(trade_date,1,4) yr, count(*) rows from market_data_lake_yahoo_archive group by 1) a using(yr)
        order by 1"""))
    w = q("""select substr(trade_date,1,4) yr, count(*) n from market_data_lake where source='nse_bhavcopy_raw' and trade_date>='2020-01-01'
             and trade_date<='2026-09-30' group by 1""")
    st = q("""select substr(trade_date,1,4) yr, count(*) n from market_data_lake_staging where series='EQ' and trade_date>='2020-01-01'
              and trade_date<='2026-09-30' group by 1""")
    if not w.equals(st):
        fails.append("window rows per year differ from staging")
    # 2. continuity across the base change
    rows = []
    for s in ("RELIANCE", "HDFCBANK", "KOTAKBANK"):
        d = q("select trade_date, close_raw from market_data_lake where symbol=? and trade_date between '2019-12-20' and '2020-01-10' order by 1", s)
        before, after = d[d.trade_date <= "2019-12-31"].iloc[-1], d[d.trade_date >= "2020-01-01"].iloc[0]
        rows.append({"symbol": s, "last_2019": before.trade_date, "close": before.close_raw, "first_2020": after.trade_date,
                     "close_2020": after.close_raw, "ratio": round(after.close_raw / before.close_raw, 4)})
        if not 0.9 < rows[-1]["ratio"] < 1.1:
            fails.append(f"{s} jump at 2020-01-01")
    sec("Continuity at the 2019-12-31 -> 2020-01-01 base change", pd.DataFrame(rows))
    # 3. big overnight jumps at the boundary across all symbols
    j = q("""select count(*) n_symbols, sum(abs(b.close_raw/a.close_raw-1) > 0.25) over_25pct from market_data_lake a
             join market_data_lake b on b.symbol=a.symbol and b.trade_date=(select min(trade_date) from market_data_lake where trade_date>='2020-01-01')
             where a.trade_date=(select max(trade_date) from market_data_lake where trade_date<'2020-01-01')
             and a.symbol not in ('NIFTY50_INDEX','INDIA_VIX')""")
    sec("All symbols present on both sides of 2019-12-31 | 2020-01-01: close ratio beyond +-25% (splits/bonuses on that day aside)", j)
    # 4. index series gaps against the equity calendar
    for s in ("NIFTY50_INDEX", "INDIA_VIX"):
        g = q("""select count(*) missing, group_concat(d) dates from (select distinct trade_date d from market_data_lake_staging
                 where trade_date >= (select min(trade_date) from market_data_lake where symbol=?) and trade_date <= '2026-09-30'
                 and trade_date not in (select trade_date from market_data_lake where symbol=?))""", s, s)
        sec(f"{s}: equity session dates (to 2026-09-30) without an index row", g)
        if int(g.missing[0]):
            fails.append(f"{s} still has gaps")
    # 5. labels / provenance
    sec("Lake rows by source label", q("select coalesce(source,'(unlabelled, pre-F2)') source, count(*) rows, min(trade_date) first, max(trade_date) last from market_data_lake group by 1"))
    # 6. mapping: leftovers and listing-age sanity
    left = q("""select count(*) rows_left_under_renamed_symbol from market_data_lake l join isin_symbol_map m on m.symbol=l.symbol and m.isin_class='pure_rename'
                and m.canonical_symbol<>m.symbol and l.trade_date between m.first_date and m.last_date""")
    sec("Rows still under a renamed traded symbol (should be 0)", left)
    if int(left.iloc[0, 0]):
        fails.append("rows left under renamed symbols")
    age = q("""select m.canonical_symbol symbol, min(l.trade_date) first_lake_date, sm.listing_date
               from (select distinct canonical_symbol from isin_symbol_map where isin_class='pure_rename' and canonical_symbol<>symbol) m
               join market_data_lake l on l.symbol=m.canonical_symbol left join securities_master sm on sm.symbol=m.canonical_symbol
               group by 1""")
    age["lake_start_before_listing"] = age.apply(lambda r: bool(r.listing_date and r.first_lake_date < str(r.listing_date)[:10]), axis=1)
    age["no_listing_date"] = age.listing_date.isna()
    sec("Listing-age gate input for the renamed names (securities_master listing date vs first lake date)",
        pd.DataFrame([{"renamed_names": len(age), "with_listing_date": int((~age.no_listing_date).sum()),
                       "no_listing_date_uses_first_lake_date": int(age.no_listing_date.sum()),
                       "lake_history_starts_before_listing_date": int(age.lake_start_before_listing.sum())}]))
    sec("Examples: lake history starts before the master's listing date", age[age.lake_start_before_listing].head(15))
    # 7. no duplicates
    d = q("select count(*) dup_pairs from (select symbol, trade_date from market_data_lake group by 1,2 having count(*)>1)")
    sec("Duplicate (symbol, date) pairs", d)
    if int(d.iloc[0, 0]):
        fails.append("duplicates")
    out.insert(0, f"# Post-swap report ({a.tag})\n\nDatabase: `{a.db}`.  Failures: {fails or 'none'}")
    p = ROOT / "docs" / "data_audit" / f"post_swap_report_{a.tag}.md"
    p.write_text("\n".join(out), encoding="utf-8")
    print(p, "FAILS:", fails or "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
