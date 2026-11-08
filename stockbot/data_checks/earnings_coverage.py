"""stockbot/data_checks/earnings_coverage.py — coverage of the collected earnings history by year, names with no data (Step 12). Read-only."""
import sqlite3, sys
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[2]


def main():
    con = sqlite3.connect(f"file:{ROOT / 'finsight.db'}?mode=ro", uri=True, timeout=120)
    act = pd.read_sql("select symbol, substr(trade_date,1,4) yr, count(*) n from market_data_lake group by 1,2", con)
    funds = set(pd.read_csv(ROOT / "data/reference/fund_etf_symbols.csv")["symbol"].str.upper())
    act = act[~act.symbol.str.upper().isin(funds) & ~act.symbol.isin(["NIFTY50_INDEX", "INDIA_VIX"]) & (act.n >= 100)]   # symbol-years with >=100 sessions
    smap = pd.read_sql("select lake_symbol, query_symbol from earnings_symbol_map", con)
    fin = pd.read_sql("select query_symbol, to_date, broadcast_ts, filing_ts, format from earnings_results_filing", con)
    bm = pd.read_sql("select query_symbol, bm_date, intimation_ts, is_results_meeting from earnings_board_meeting", con)
    raw = pd.read_sql("select endpoint, query_symbol, row_count from earnings_api_raw", con)
    fin["yr"] = fin.to_date.str[:4]; bm["yr"] = bm.bm_date.str[:4]
    fin["has_bc"] = fin.broadcast_ts.notna(); bm_r = bm[bm.is_results_meeting == 1].copy(); bm_r["has_int"] = bm_r.intimation_ts.notna()
    fy = fin.merge(smap, on="query_symbol").groupby(["lake_symbol", "yr"]).agg(fin_rows=("to_date", "size"), fin_bc=("has_bc", "sum")).reset_index()
    by = bm_r.merge(smap, on="query_symbol").groupby(["lake_symbol", "yr"]).agg(bm_rows=("bm_date", "size"), bm_int=("has_int", "sum")).reset_index()
    t = act.rename(columns={"symbol": "lake_symbol"}).merge(fy, on=["lake_symbol", "yr"], how="left").merge(by, on=["lake_symbol", "yr"], how="left").fillna(0)
    t["any_fin"] = t.fin_rows > 0; t["fin_bc"] = t.fin_bc > 0; t["bm"] = t.bm_rows > 0; t["bm_int"] = t.bm_int > 0; t["either"] = t.any_fin | t.bm
    cov = t.groupby("yr").agg(symbol_years=("lake_symbol", "size"), with_results_filing=("any_fin", "sum"), with_broadcast_ts=("fin_bc", "sum"),
                              with_results_meeting=("bm", "sum"), with_intimation_ts=("bm_int", "sum"), with_either=("either", "sum"))
    for c in ("with_results_filing", "with_broadcast_ts", "with_results_meeting", "with_intimation_ts", "with_either"):
        cov[c + "_pct"] = (100 * cov[c] / cov.symbol_years).round(1)
    print(cov.to_string())
    # names with no data at all
    per = raw.pivot_table(index="query_symbol", columns="endpoint", values="row_count", aggfunc="max").fillna(-1)
    nod = smap.merge(per, left_on="query_symbol", right_index=True, how="left")
    tot = nod.groupby("lake_symbol")[[c for c in per.columns]].max()
    none = tot[(tot.max(axis=1) <= 0)].index.tolist()
    last = act.groupby("symbol").yr.agg(["min", "max", "size"]).rename(columns={"size": "active_years"})
    nd = last.loc[last.index.intersection(none)].reset_index().rename(columns={"symbol": "lake_symbol", "min": "first_year", "max": "last_year"})
    out = ROOT / "docs/data_audit/earnings_no_data_symbols.csv"; nd.sort_values(["last_year", "lake_symbol"]).to_csv(out, index=False)
    print("lake symbols (>=1 active year):", act.symbol.nunique(), " with no data from either API:", len(nd), " -> ", out.name)
    print(nd.groupby("last_year").size().to_string())
    cov.to_csv(ROOT / "docs/data_audit/earnings_coverage_by_year.csv")
    q = pd.read_sql("select count(*) n, sum(broadcast_ts is not null) bc, sum(filing_ts is not null) fl, min(to_date) mn, max(to_date) mx from earnings_results_filing", con)
    print(q.to_string()); print(pd.read_sql("select count(*) n, sum(is_results_meeting) r, sum(intimation_ts is not null) i, min(bm_date) mn, max(bm_date) mx from earnings_board_meeting", con).to_string())
    print(pd.read_sql("select results_rule, count(*) from earnings_board_meeting where is_results_meeting=1 group by 1", con).to_string())


if __name__ == "__main__":
    main()
