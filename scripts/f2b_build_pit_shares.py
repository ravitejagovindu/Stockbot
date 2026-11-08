"""NOT USED (F2b closed 2026-11-08: failed its pre-registered spot-check bar; the table is not loaded and the screener does not read it). Kept for the record - see docs/data_audit/DATA_KNOWN_ISSUES.md KI-001.

scripts/f2b_build_pit_shares.py — derive point-in-time shares outstanding for every lake equity symbol (F2b).

Anchors, in order: (1) the current issued size (``shares_outstanding``, Yahoo snapshot of 2026-10-02); (2) a count read from a filing
(``data/reference/pit_shares_anchors.csv``: symbol, anchor_date, shares_count, source); (3) a same-ISIN successor's count at the predecessor's last
trading day (``isin_symbol_map``).  From the anchor the count is walked through SPLIT/BONUS (log), parsed rights (+45-day allotment lag, +-45-day band
unreliable) and treated as unreliable before mergers / unsupported events (``data/reference/unadjusted_events.csv``); demergers are share-neutral.
Creates/fills ``shares_outstanding_pit`` (additive) unless --dry-run, and writes docs/data_audit/pit_shares_coverage<tag>.csv.
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
from data.ingestion.pit_shares import derive_segments, parse_rights_ratio, rights_factor, shares_on      # noqa: E402
from engine_core.adjustments import action_factor                                                         # noqa: E402

OUT = ROOT / "docs" / "data_audit"
SNAPSHOT = date(2026, 10, 2)
NEUTRAL = {"demerger"}
DDL = """create table if not exists shares_outstanding_pit (
 id integer primary key autoincrement, symbol varchar(20) not null, effective_date date not null, shares_count bigint not null,
 reliable integer not null default 1, basis varchar(300), derived_at varchar(40), unique(symbol, effective_date))"""


def lake_symbols(con) -> pd.DataFrame:
    funds = set(pd.read_csv(ROOT / "data/reference/fund_etf_symbols.csv")["symbol"].str.upper())
    d = pd.read_sql_query("select symbol, substr(trade_date,1,4) y, max(trade_date) last_d, sum(close_raw*volume_raw) tv, count(*) n "
                          "from market_data_lake where symbol not in ('NIFTY50_INDEX','INDIA_VIX') and trade_date <= '2026-09-30' group by 1,2", con)
    return d[~d["symbol"].str.upper().isin(funds)].copy()


def build(con: sqlite3.Connection, lake: pd.DataFrame):
    cur = pd.read_sql_query("select symbol, shares_count, source from shares_outstanding", con)
    ev = pd.read_sql_query("select symbol, ex_date, action_type, ratio_numerator, ratio_denominator from corporate_actions_log "
                           "where action_type in ('SPLIT','BONUS')", con)
    ua = pd.read_csv(ROOT / "data/reference/unadjusted_events.csv")
    ua = ua[~ua["kind"].isin(NEUTRAL)]
    splits: dict[str, list] = {}
    for r in ev.itertuples():
        f = action_factor({"action_type": r.action_type, "ratio_numerator": r.ratio_numerator, "ratio_denominator": r.ratio_denominator})
        splits.setdefault(r.symbol, []).append((date.fromisoformat(r.ex_date), float(f)))
    rights: dict[str, list] = {}
    last_ua: dict[str, date] = {}
    for r in ua.itertuples():
        d = date.fromisoformat(r.date)
        ratio = parse_rights_ratio(r.detail) if r.kind == "large_rights" else None
        if ratio:
            rights.setdefault(r.lake_symbol, []).append((d, rights_factor(*ratio)))
        else:
            last_ua[r.lake_symbol] = max(d, last_ua.get(r.lake_symbol, date.min))
    anchors_f = ROOT / "data/reference/pit_shares_anchors.csv"
    anch = pd.read_csv(anchors_f) if anchors_f.exists() else pd.DataFrame(columns=["symbol", "anchor_date", "shares_count", "source"])
    imap = pd.read_sql_query("select isin, canonical_symbol from isin_symbol_map", con)
    last_day = lake.groupby("symbol")["last_d"].max().to_dict()
    now = datetime.now().isoformat(timespec="seconds")
    segs: dict[str, list] = {}
    how: dict[str, str] = {}

    def make(sym, shares, adate, rel, label):
        s = derive_segments(int(shares), splits.get(sym, []), last_ua.get(sym), rights=rights.get(sym, []), anchor_date=adate, anchor_reliable=rel)
        segs[sym], how[sym] = s, label

    for r in cur.itertuples():
        make(r.symbol, r.shares_count, SNAPSHOT, True, f"current issued size ({r.source}, {SNAPSHOT})")
    for sym, g in anch.groupby("symbol"):                                 # filing anchors: the nearest anchor in time governs each date
        if sym in segs:
            continue
        series = [(date.fromisoformat(r.anchor_date),
                   derive_segments(int(r.shares_count), splits.get(sym, []), last_ua.get(sym), rights=rights.get(sym, []),
                                   anchor_date=date.fromisoformat(r.anchor_date))) for r in g.itertuples()]
        pts = sorted({d for _, sg in series for d, _, _ in sg})
        out = []
        for p in pts:
            ad, sg = min(series, key=lambda t: (abs((t[0] - p).days), t[0]))
            x = shares_on(sg, p)
            out.append((p, x[0], x[1]))
        merged = [out[0]] + [o for prev, o in zip(out, out[1:]) if (o[1], o[2]) != (prev[1], prev[2])]
        segs[sym] = merged
        how[sym] = "filing anchors " + "; ".join(f"{r.shares_count} on {r.anchor_date}" for r in g.itertuples())
    for sym in sorted(set(lake["symbol"]) - set(segs)):                  # successors through the same ISIN
        isins = set(imap[imap["canonical_symbol"] == sym]["isin"])
        succ = sorted(set(imap[imap["isin"].isin(isins) & (imap["canonical_symbol"] != sym)]["canonical_symbol"]) & set(segs))
        if succ and sym in last_day:
            y, ld = succ[0], date.fromisoformat(last_day[sym])
            x = shares_on(segs[y], ld)
            if x:
                make(sym, x[0], ld, bool(x[1]), f"successor {y} (same ISIN) count {x[0]} on {ld}")
    rows = []
    for sym, s in segs.items():
        ne = len(splits.get(sym, [])); nr = len(rights.get(sym, []))
        basis = f"{how[sym]}; {ne} SPLIT/BONUS, {nr} rights" + (f"; unreliable before {last_ua[sym]}" if sym in last_ua else "")
        rows += [(sym, d.isoformat(), n, rel, basis[:300], now) for d, n, rel in s]
    return rows, segs, how


def coverage(lake: pd.DataFrame, segs, how):
    def status(r):
        s = segs.get(r.symbol)
        if s is None:
            return "no_shares_source"
        x = shares_on(s, date.fromisoformat(r.last_d))
        return "pit_reliable" if x and x[1] == 1 else "excluded_unreliable"
    d = lake.copy()
    d["status"] = [status(r) for r in d.itertuples()]
    d["anchor"] = [" ".join(how[s].split(" ")[:2]) if s in how else "none" for s in d["symbol"]]
    blocks = []
    for name, sub in (("all", d), ("ADTV25", d[d["tv"] / d["n"] >= 25e7])):
        t = sub.pivot_table(index="y", columns="status", values="symbol", aggfunc="count", fill_value=0)
        v = sub.pivot_table(index="y", columns="status", values="tv", aggfunc="sum", fill_value=0)
        pct = (v.div(v.sum(axis=1), axis=0) * 100).round(2)
        for col in ("pit_reliable", "excluded_unreliable", "no_shares_source"):
            for tab in (t, pct):
                if col not in tab:
                    tab[col] = 0
        blocks += [t.add_prefix(f"{name}_n_"), pct.add_prefix(f"{name}_pct_tv_")]
    return pd.concat(blocks, axis=1).reset_index().rename(columns={"y": "year"}), d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=120) if a.dry_run else sqlite3.connect(a.db, timeout=120)
    lake = lake_symbols(con)
    rows, segs, how = build(con, lake)
    cov, detail = coverage(lake, segs, how)
    OUT.mkdir(exist_ok=True)
    cov.to_csv(OUT / f"pit_shares_coverage{a.tag}.csv", index=False)
    detail[detail["status"] != "pit_reliable"].sort_values("tv", ascending=False).to_csv(OUT / f"pit_shares_excluded_symbol_years{a.tag}.csv", index=False)
    pd.set_option("display.width", 250)
    print(cov[["year"] + [c for c in cov.columns if c.startswith("ADTV25_pct_tv_")]].to_string(index=False))
    print(f"segments: {len(rows)} for {len(segs)} symbols;", pd.Series([h.split(" ")[0] for h in how.values()]).value_counts().to_dict())
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
