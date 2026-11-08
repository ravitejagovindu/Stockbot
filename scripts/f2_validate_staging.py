"""scripts/f2_validate_staging.py — F2 STOP-1 evidence: validate the Bhavcopy staging table BEFORE any swap.

Read-only on the database. Produces (in docs/data_audit/):
  F2_staging_validation_report.md      human-readable report
  staging_vs_lake_by_year.csv          row counts / symbol overlap / volume + price ratio per year
  factor_crosscheck.csv                A1: log factor vs Bhavcopy previous-close factor vs Yahoo/raw ratio factor
  symbol_map.csv                       A3: ISIN-based renames / symbol changes
  historical_universe.csv              A4: universe built from the daily files (incl. delisted names)
  unexplained_moves.csv                |close-to-close| moves > 40% without a logged corporate action (disposition col)
Usage: py -3 scripts/f2_validate_staging.py [--db finsight.db] [--actions-csv data/reference/nse_corporate_actions_raw.csv]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.ingestion.nse_corporate_actions_history import _parse_ex, parse_subject  # noqa: E402
from stockbot.data.adjustments import action_factor  # noqa: E402

OUT = ROOT / "docs" / "data_audit"
SWAP_FROM, SWAP_TO = "2020-01-01", "2026-09-30"
IDX = ("NIFTY50_INDEX", "INDIA_VIX")


def md(df: pd.DataFrame) -> str:
    """Tiny markdown table writer (no tabulate dependency)."""
    if df is None or len(df) == 0:
        return "(none)"
    cols = list(df.columns)
    fmt = lambda v: f"{v:.4f}" if isinstance(v, float) else str(v)  # noqa: E731
    rows = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    rows += ["| " + " | ".join(fmt(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(rows)


def connect(db: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    return con


def load_actions(csv_path: Path) -> pd.DataFrame:
    """Parsed split/bonus/rights/demerger/merger rows with factors (NaN when no price factor applies)."""
    raw = pd.read_csv(csv_path)
    rows = []
    for r in raw.itertuples():
        ex = _parse_ex(r.exDate)
        if ex is None:
            continue
        sym = str(r.symbol or r.query_symbol).strip()
        for a in parse_subject(str(r.subject)):
            if a["action_type"] == "DIVIDEND":
                continue
            fac = np.nan
            if a["action_type"] in ("SPLIT", "BONUS"):
                fac = action_factor({"action_type": a["action_type"], "ratio_numerator": a["num"],
                                     "ratio_denominator": a["den"]})
            rows.append({"symbol": sym, "ex_date": ex.isoformat(), "action_type": a["action_type"], "factor": fac,
                         "isin": r.isin, "subject": str(r.subject).strip()})
    return pd.DataFrame(rows).drop_duplicates(["symbol", "ex_date", "action_type"])


def fetch_log_summary(con) -> pd.DataFrame:
    return pd.read_sql(
        "select substr(trade_date,1,4) as year, status, count(*) n, sum(n_rows) rows_total "
        "from bhavcopy_fetch_log group by 1,2 order by 1,2", con)


def calendar_crosscheck(con) -> pd.DataFrame:
    """Nifty trade dates in the lake vs dates with Bhavcopy rows (misses = possible download gaps)."""
    nifty = pd.read_sql("select trade_date from market_data_lake where symbol='NIFTY50_INDEX'", con)["trade_date"]
    stg = pd.read_sql("select trade_date from bhavcopy_fetch_log where status='OK'", con)["trade_date"]
    nifty, stg = set(nifty), set(stg)
    lo = pd.read_sql("select min(trade_date) a from bhavcopy_fetch_log where status='OK'", con)["a"][0]
    nifty = {d for d in nifty if d >= lo}
    return pd.DataFrame({
        "nifty_dates_without_bhavcopy": [len(nifty - stg)],
        "bhavcopy_dates_without_nifty": [len(stg - nifty)],
        "example_missing": [",".join(sorted(nifty - stg)[:15])],
    })


def staging_vs_lake(con) -> pd.DataFrame:
    q = f"""
    select substr(s.trade_date,1,4) as year,
           count(*) n_matched,
           avg(case when s.volume_raw = m.volume_raw then 1.0 else 0.0 end) vol_equal_rate,
           avg(case when abs(m.close_raw / s.close_raw - 1) < 0.002 then 1.0 else 0.0 end) close_within_0_2pct,
           avg(m.close_raw / s.close_raw) mean_old_over_new,
           min(m.close_raw / s.close_raw) min_old_over_new
    from market_data_lake_staging s
    join market_data_lake m on m.symbol = s.symbol and m.trade_date = s.trade_date
    where s.trade_date between '{SWAP_FROM}' and '{SWAP_TO}'
    group by 1 order by 1"""
    matched = pd.read_sql(q, con)
    cnt = pd.read_sql(f"""
    select y.year, s_n staging_rows, l_n lake_rows from (
      select substr(trade_date,1,4) year, count(*) s_n from market_data_lake_staging
      where trade_date between '{SWAP_FROM}' and '{SWAP_TO}' group by 1) y
    join (select substr(trade_date,1,4) year, count(*) l_n from market_data_lake
          where trade_date between '{SWAP_FROM}' and '{SWAP_TO}' and symbol not in ('NIFTY50_INDEX','INDIA_VIX')
          group by 1) l on l.year = y.year""", con)
    return cnt.merge(matched, on="year", how="left")


def symbol_overlap(con) -> dict:
    sql = f"""select count(distinct symbol) from {{t}} where trade_date between '{SWAP_FROM}' and '{SWAP_TO}'"""
    stg = con.execute(sql.format(t="market_data_lake_staging")).fetchone()[0]
    lake = con.execute(sql.format(t="market_data_lake") + " and symbol not in ('NIFTY50_INDEX','INDIA_VIX')").fetchone()[0]
    both = con.execute(f"""select count(*) from (select distinct symbol from market_data_lake_staging
        where trade_date between '{SWAP_FROM}' and '{SWAP_TO}') s
        where s.symbol in (select distinct symbol from market_data_lake where trade_date between '{SWAP_FROM}' and '{SWAP_TO}')""").fetchone()[0]
    only_lake = pd.read_sql(f"""select distinct symbol from market_data_lake where trade_date between '{SWAP_FROM}' and '{SWAP_TO}'
        and symbol not in ('NIFTY50_INDEX','INDIA_VIX')
        and symbol not in (select distinct symbol from market_data_lake_staging)""", con)["symbol"].tolist()
    return {"staging_symbols": stg, "lake_symbols": lake, "in_both": both, "only_in_lake": only_lake}


def factor_crosscheck(con, actions: pd.DataFrame) -> pd.DataFrame:
    """A1. For each split/bonus (log) compute: bhav factor = PrevClose(ex)/Close(prev session) from Bhavcopy, and
    the Yahoo/raw factor = ratio(prev)/ratio(ex) with ratio = lake_close/staging_close (only 2020-2026)."""
    out = []
    px = actions[actions["factor"].notna()]
    for (sym, ex), g in px.groupby(["symbol", "ex_date"]):
        log_f = float(np.prod(g["factor"]))
        rows = pd.read_sql(
            "select trade_date, close_raw, prev_close from market_data_lake_staging where symbol=? "
            "and trade_date between date(?, '-12 day') and date(?, '+3 day') order by trade_date",
            con, params=(sym, ex, ex))
        if rows.empty:
            out.append({"symbol": sym, "ex_date": ex, "log_factor": log_f, "bhav_factor": np.nan, "close_ratio_factor": np.nan, "yahoo_factor": np.nan})
            continue
        on = rows[rows["trade_date"] >= ex].head(1)
        prev = rows[rows["trade_date"] < ex].tail(1)
        bhav = (float(on["prev_close"].iloc[0]) / float(prev["close_raw"].iloc[0])
                if len(on) and len(prev) and pd.notna(on["prev_close"].iloc[0]) else np.nan)
        cf = (float(on["close_raw"].iloc[0]) / float(prev["close_raw"].iloc[0])) if len(on) and len(prev) else np.nan
        yf = np.nan
        if len(on) and len(prev) and SWAP_FROM <= ex <= SWAP_TO:
            m = pd.read_sql("select trade_date, close_raw from market_data_lake where symbol=? and trade_date in (?,?)",
                            con, params=(sym, on["trade_date"].iloc[0], prev["trade_date"].iloc[0])).set_index("trade_date")["close_raw"]
            if len(m) == 2:
                r_on = m[on["trade_date"].iloc[0]] / float(on["close_raw"].iloc[0])
                r_prev = m[prev["trade_date"].iloc[0]] / float(prev["close_raw"].iloc[0])
                yf = r_prev / r_on
        out.append({"symbol": sym, "ex_date": ex, "log_factor": log_f, "bhav_factor": bhav, "close_ratio_factor": cf, "yahoo_factor": yf})
    df = pd.DataFrame(out)
    if df.empty:
        return df
    tol = 0.03  # 3% (cash dividends and price moves confound the previous-close signal)
    df["bhav_agrees"] = (df["bhav_factor"] / df["log_factor"] - 1).abs() < tol
    # NSE's PrevClose field is NOT adjusted for splits/bonuses (bhav_factor ~1.0), so the independent price evidence is the
    # raw close-to-close ratio across the ex-date (20% tolerance: it also contains one day of ordinary price movement)
    df["close_ratio_agrees"] = (df["close_ratio_factor"] / df["log_factor"] - 1).abs() < 0.20
    df["yahoo_agrees"] = (df["yahoo_factor"] / df["log_factor"] - 1).abs() < tol
    return df


def symbol_map(con) -> pd.DataFrame:
    d = pd.read_sql("select isin, symbol, min(trade_date) first_date, max(trade_date) last_date, count(*) n_days "
                    "from market_data_lake_staging where isin is not null and isin!='nan' group by isin, symbol", con)
    multi = d.groupby("isin")["symbol"].nunique()
    multi = multi[multi > 1].index
    return d[d["isin"].isin(multi)].sort_values(["isin", "first_date"])


def historical_universe(con) -> pd.DataFrame:
    df = pd.read_sql("select symbol, min(trade_date) first_date, max(trade_date) last_date, count(*) n_days, "
                     "max(isin) isin from market_data_lake_staging group by symbol", con)
    last = pd.read_sql("select max(trade_date) m from market_data_lake_staging", con)["m"][0]
    cutoff = (datetime.fromisoformat(last) - timedelta(days=30)).date().isoformat()
    df["delisted_or_renamed_before_end"] = df["last_date"] < cutoff
    return df


def unexplained_moves(con, actions: pd.DataFrame, thr: float = 0.40) -> pd.DataFrame:
    # filter inside SQLite so only the (few) large moves ever reach pandas (memory)
    q = f"""select * from (
              select symbol, trade_date, close_raw, prev_close,
                     lag(close_raw) over (partition by symbol order by trade_date) pc
              from market_data_lake_staging)
            where pc > 0 and abs(close_raw / pc - 1) > {thr}"""
    big = pd.read_sql(q, con)
    big["move"] = big["close_raw"] / big["pc"] - 1
    ex = {(r.symbol, r.ex_date) for r in actions.itertuples()}
    exd = actions.groupby("symbol")["ex_date"].apply(list).to_dict()

    def near_action(r):
        for e in exd.get(r.symbol, []):
            if abs((date.fromisoformat(r.trade_date) - date.fromisoformat(e)).days) <= 3:
                return e
        return ""

    big["nearest_logged_action"] = [near_action(r) for r in big.itertuples()]
    big["disposition"] = np.where(big["nearest_logged_action"] != "", "explained (logged action within 3 days)", "OPEN")
    # NSE reference price (PrevClose) equal to yesterday's close means no exchange-side adjustment: likely a real move
    big["nse_prev_close_adjusted"] = ((big["prev_close"] / big["pc"] - 1).abs() > 0.02)
    big["penny_or_illiquid"] = np.minimum(big["close_raw"], big["pc"]) < 5
    return big.sort_values(["disposition", "trade_date"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--actions-csv", default=str(ROOT / "data" / "reference" / "nse_corporate_actions_raw.csv"))
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect(args.db)
    lines = ["# F2 — Bhavcopy staging validation report", "", f"Generated {datetime.now():%Y-%m-%d %H:%M}.", ""]

    fl = fetch_log_summary(con)
    lines += ["## 1. Download log (by year and status)", "", md(fl), ""]
    cc = calendar_crosscheck(con)
    lines += ["## 2. Trading-calendar cross-check against the lake's Nifty dates", "", md(cc), ""]

    sv = staging_vs_lake(con)
    sv.to_csv(OUT / "staging_vs_lake_by_year.csv", index=False)
    so = symbol_overlap(con)
    lines += ["## 3. Staging (true raw) vs current lake (Yahoo-adjusted) for 2020-01-01..2026-09-30", "",
              md(sv), "",
              f"Symbols: staging {so['staging_symbols']}, lake {so['lake_symbols']}, in both {so['in_both']}, "
              f"only in lake {len(so['only_in_lake'])} (e.g. {', '.join(so['only_in_lake'][:25])}).", "",
              "Reading: `mean_old_over_new` < 1 and `close_within_0_2pct` far below 1 in early years shows the old lake rows "
              "are adjusted (split/bonus/dividend); `vol_equal_rate` shows whether Yahoo volumes equal NSE volumes.", ""]

    sm = symbol_map(con)
    sm.to_csv(OUT / "symbol_map.csv", index=False)
    lines += ["## 4. Symbol continuity (A3) — ISINs traded under more than one symbol", "",
              f"{sm['isin'].nunique()} ISINs / {len(sm)} symbol segments (see symbol_map.csv). First 25:", "",
              md(sm.head(25)) if len(sm) else "none", ""]

    hu = historical_universe(con)
    hu.to_csv(OUT / "historical_universe.csv", index=False)
    by_year = pd.read_sql("select substr(trade_date,1,4) year, count(distinct symbol) symbols from market_data_lake_staging group by 1", con)
    pre2020 = int(((hu["first_date"] < "2020-01-01")).sum())
    lines += ["## 5. Historical universe from the daily files (A4)", "",
              f"{len(hu)} distinct EQ symbols; {pre2020} have raw data before 2020; "
              f"{int(hu['delisted_or_renamed_before_end'].sum())} stop trading (delisted or renamed) before the end.", "",
              md(by_year), ""]

    ap_path = Path(args.actions_csv)
    if ap_path.exists():
        acts = load_actions(ap_path)
        fx = factor_crosscheck(con, acts)
        fx.to_csv(OUT / "factor_crosscheck.csv", index=False)
        n = len(fx)
        lines += ["## 6. Corporate-action factor cross-check (A1)", "",
                  f"{n} split/bonus ex-dates in the NSE feed. Agreement: raw close-to-close ratio across the ex-date (within 20%) "
                  f"{int(fx['close_ratio_agrees'].sum())}/{int(fx['close_ratio_factor'].notna().sum())}; NSE PrevClose field "
                  f"(within 3%) {int(fx['bhav_agrees'].sum())}/{n} (the field is not adjusted by NSE, so it carries no information); Yahoo/raw ratio factor {int(fx['yahoo_agrees'].sum())}/"
                  f"{int(fx['yahoo_factor'].notna().sum())} (2020-2026 only). Disagreements: see factor_crosscheck.csv.", ""]
        um = unexplained_moves(con, acts)
        um.to_csv(OUT / "unexplained_moves.csv", index=False)
        lines += ["## 7. Large close-to-close moves (>40%) in staging", "",
                  f"{len(um)} moves; {(um['disposition'] == 'OPEN').sum()} OPEN (no logged action within 3 days), of which "
                  f"{int(((um['disposition'] == 'OPEN') & ~um['penny_or_illiquid']).sum())} have a price of at least Rs5 on both days. "
                  "See unexplained_moves.csv (disposition column to be completed by hand).", ""]
    else:
        lines += ["## 6/7. Factor cross-check and unexplained moves", "",
                  f"Skipped: {ap_path} not found (run the corporate-actions dump first).", ""]
    (OUT / "F2_staging_validation_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT / "F2_staging_validation_report.md")


if __name__ == "__main__":
    main()
