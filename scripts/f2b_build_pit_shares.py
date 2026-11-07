"""scripts/f2b_build_pit_shares.py — derive point-in-time shares outstanding for every lake equity symbol (F2b).

Current issued size (``shares_outstanding``, one Yahoo snapshot per symbol, fetched 2026-10-02) is walked back through the SPLIT/BONUS rows
of ``corporate_actions_log`` (``data/ingestion/pit_shares.py``).  Segments dated before an unadjustable event are flagged unreliable.
Creates/fills ``shares_outstanding_pit`` (additive; the old snapshot table is untouched) unless --dry-run, and writes
docs/data_audit/pit_shares_coverage.csv/.md (coverage by year, excluded names, share of traded value).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.ingestion.pit_shares import derive_segments, shares_on        # noqa: E402
from engine_core.adjustments import action_factor                       # noqa: E402

OUT = ROOT / "docs" / "data_audit"
DDL = """create table if not exists shares_outstanding_pit (
 id integer primary key autoincrement, symbol varchar(20) not null, effective_date date not null, shares_count bigint not null,
 reliable integer not null default 1, basis varchar(300), derived_at varchar(40), unique(symbol, effective_date))"""


def build(con: sqlite3.Connection, neutral_kinds: tuple = ()):
    cur = pd.read_sql_query("select symbol, shares_count, source from shares_outstanding", con)
    ev = pd.read_sql_query("select symbol, ex_date, action_type, ratio_numerator, ratio_denominator from corporate_actions_log "
                           "where action_type in ('SPLIT','BONUS')", con)
    ua = pd.read_csv(ROOT / "data/reference/unadjusted_events.csv")
    ua = ua[~ua["kind"].isin(neutral_kinds)]
    last_ua = ua.groupby("lake_symbol")["date"].max().to_dict()
    evs: dict[str, list] = {}
    for r in ev.itertuples():
        f = action_factor({"action_type": r.action_type, "ratio_numerator": r.ratio_numerator, "ratio_denominator": r.ratio_denominator})
        evs.setdefault(r.symbol, []).append((date.fromisoformat(r.ex_date), float(f)))
    now = datetime.now().isoformat(timespec="seconds")
    rows, segs = [], {}
    for r in cur.itertuples():
        lu = date.fromisoformat(last_ua[r.symbol]) if r.symbol in last_ua else None
        s = derive_segments(int(r.shares_count), evs.get(r.symbol, []), lu)
        segs[r.symbol] = s
        basis = f"current issued size {int(r.shares_count)} ({r.source}) walked back through {len(evs.get(r.symbol, []))} SPLIT/BONUS date(s)" + \
                (f"; unreliable before {lu} (unadjusted event)" if lu else "")
        rows += [(r.symbol, d.isoformat(), n, rel, basis, now) for d, n, rel in s]
    return rows, segs


def coverage(con, segs):
    funds = set(pd.read_csv(ROOT / "data/reference/fund_etf_symbols.csv")["symbol"].str.upper())
    q = ("select symbol, substr(trade_date,1,4) y, max(trade_date) last_d, sum(close_raw*volume_raw) tv, count(*) n from market_data_lake "
         "where symbol not in ('NIFTY50_INDEX','INDIA_VIX') and trade_date <= '2026-09-30' group by 1,2")
    d = pd.read_sql_query(q, con)
    d = d[~d["symbol"].str.upper().isin(funds)]
    def status(r):
        s = segs.get(r.symbol)
        if s is None:
            return "no_current_shares"
        x = shares_on(s, date.fromisoformat(r.last_d))
        return "pit_reliable" if x and x[1] == 1 else "excluded_unadjusted_event"
    d["status"] = [status(r) for r in d.itertuples()]
    t = d.pivot_table(index="y", columns="status", values="symbol", aggfunc="count", fill_value=0)
    v = d.pivot_table(index="y", columns="status", values="tv", aggfunc="sum", fill_value=0)
    share = (v.div(v.sum(axis=1), axis=0) * 100).round(2).add_suffix("_pct_traded_value")
    out = pd.concat([t, share], axis=1)
    el = d[d["tv"] / d["n"] >= 25e7]                                    # symbol-years averaging >= Rs25 crore a day (ADTV gate level)
    te = el.pivot_table(index="y", columns="status", values="symbol", aggfunc="count", fill_value=0).add_suffix("_ADTV25")
    ve = el.pivot_table(index="y", columns="status", values="tv", aggfunc="sum", fill_value=0)
    se = (ve.div(ve.sum(axis=1), axis=0) * 100).round(2).add_suffix("_ADTV25_pct_traded_value")
    out = pd.concat([out, te, se], axis=1).reset_index().rename(columns={"y": "year"})
    return out, d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--neutral-kinds", default="", help="unadjusted-event kinds treated as share-count neutral (what-if only)")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    con = sqlite3.connect(a.db, timeout=120)
    rows, segs = build(con, tuple(k for k in a.neutral_kinds.split(',') if k))
    cov, detail = coverage(con, segs)
    OUT.mkdir(exist_ok=True)
    cov.to_csv(OUT / f"pit_shares_coverage{a.tag}.csv", index=False)
    detail[detail["status"] != "pit_reliable"].sort_values("tv", ascending=False).to_csv(OUT / f"pit_shares_excluded_symbol_years{a.tag}.csv", index=False)
    print(cov.to_string(index=False))
    print(f"segments: {len(rows)} for {len(segs)} symbols")
    if not a.dry_run:
        with con:
            con.execute(DDL)
            n0 = con.execute("select count(*) from shares_outstanding_pit").fetchone()[0]
            assert n0 == 0, f"shares_outstanding_pit already holds {n0} rows: refusing to append twice"
            con.executemany("insert into shares_outstanding_pit(symbol,effective_date,shares_count,reliable,basis,derived_at) values (?,?,?,?,?,?)", rows)
            n1 = con.execute("select count(*) from shares_outstanding_pit").fetchone()[0]
            assert n1 == len(rows), (n1, len(rows))
        print("loaded", n1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
