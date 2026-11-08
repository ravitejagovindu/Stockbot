"""stockbot/data/ingestion/f2_event_evidence.py — evidence tier for every corporate-action event in the NSE dump (F2 Step 4).  Read-only on the DB.

Events are matched to raw price rows BY ISIN (NSE keys its history to the current symbol; staging keeps the traded symbol), so
renamed companies are covered without extra symbol queries.  Yahoo factors come from market_data_lake_yahoo_archive (the
pre-swap Yahoo-adjusted rows, 2020..2026-09) vs the raw staging close on the same days.
Output: data/reference/corporate_actions_evidence.csv (one row per parsed event) + docs/data_audit/event_evidence_summary.md
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
from stockbot.data.ingestion.ca_evidence import best_pair, classify          # noqa: E402
from stockbot.data.ingestion.nse_corporate_actions_history import _parse_ex, parse_subject   # noqa: E402
from stockbot.data.adjustments import action_factor                    # noqa: E402

YAHOO_FROM, YAHOO_TO = "2020-01-01", "2026-09-30"


def parse_events(raw_csv: Path) -> pd.DataFrame:
    raw = pd.read_csv(raw_csv)
    rows = []
    for r in raw.itertuples():
        ex = _parse_ex(r.exDate)
        if ex is None:
            continue
        sym = str(r.symbol or r.query_symbol).strip()
        isin = r.isin if isinstance(r.isin, str) and r.isin.startswith(("IN", "XS")) else None
        for a in parse_subject(str(r.subject)):
            f = np.nan
            if a["action_type"] in ("SPLIT", "BONUS"):
                f = action_factor({"action_type": a["action_type"], "ratio_numerator": a["num"], "ratio_denominator": a["den"]})
            rows.append({"symbol": sym, "isin": isin, "ex_date": ex.isoformat(), "action_type": a["action_type"],
                         "num": a["num"], "den": a["den"], "factor": f, "note": a["note"], "subject": str(r.subject).strip()})
    return pd.DataFrame(rows).drop_duplicates(["symbol", "ex_date", "action_type"]).reset_index(drop=True)


def canonical(con, isin, sym, ex) -> str:
    if isin:
        r = con.execute("select canonical_symbol from isin_symbol_map where isin=? and first_date<=? and last_date>=?", (isin, ex, ex)).fetchone()
        if r:
            return r[0]
        r = con.execute("select canonical_symbol from isin_symbol_map where isin=? order by last_date desc limit 1", (isin,)).fetchone()
        if r:
            return r[0]
    return sym


def evidence_for(con, g: pd.DataFrame) -> dict:
    sym, isin, ex = g["symbol"].iloc[0], g["isin"].iloc[0], g["ex_date"].iloc[0]
    isin = None if pd.isna(isin) else isin
    f = float(np.prod(g["factor"]))
    # NSE issues a NEW ISIN at a face-value split (360ONE INE466L01020 -> INE466L01038), so an ISIN alone loses the ex-date:
    # match on the ISIN or on any traded symbol of that ISIN (rename history from the map) or the event's own symbol.
    syms = {sym}
    if isin:
        syms |= {r[0] for r in con.execute("select symbol from isin_symbol_map where isin=?", (isin,))}
    ph = ",".join("?" * len(syms))
    where, par = f"(isin = ? or symbol in ({ph}))", [isin or "-"] + sorted(syms)
    px = pd.read_sql_query(f"select trade_date, close_raw, volume_raw, symbol from market_data_lake_staging where {where} "
                           f"and trade_date between date(?, '-14 day') and date(?, '+14 day') order by trade_date, volume_raw desc",
                           con, params=par + [ex, ex]).drop_duplicates("trade_date")
    dates, close, tsym = list(px.trade_date), list(px.close_raw), list(px.symbol)
    pre_sym = pre_date = None
    after = [i for i, d in enumerate(dates) if d >= ex]
    raw_ratio = off = None
    yf = None
    pair = None
    if after:
        i0 = after[0]
        raw_ratio, off = best_pair(dates, close, i0, f)
        if off is not None:
            t = i0 + off
            pair = (dates[t - 1], dates[t])
            pre_sym, pre_date = tsym[t - 1], dates[t - 1]
            if YAHOO_FROM <= dates[t] <= YAHOO_TO:
                cs = canonical(con, isin, sym, ex)
                a = {d: c for d, c in con.execute("select trade_date, close_raw from market_data_lake_yahoo_archive where symbol=? and trade_date in (?,?)",
                                                 (cs, *pair))}
                if len(a) == 2:
                    yf = (a[pair[0]] / close[t - 1]) / (a[pair[1]] / close[t])
    basis = "ex-date window (+-2 sessions)"
    if raw_ratio is None:
        # no EQ-series rows on both sides of the ex-date: if the stock re-enters EQ after a gap an unadjusted split would make a false
        # step at re-entry, so use the ratio across the gap (last close before the ex-date vs first close on/after it)
        pre = con.execute(f"select trade_date, close_raw from market_data_lake_staging where {where} and trade_date < ? "
                          f"and trade_date >= date(?, '-800 day') order by trade_date desc, volume_raw desc limit 1", par + [ex, ex]).fetchone()
        post = con.execute(f"select trade_date, close_raw from market_data_lake_staging where {where} and trade_date >= ? "
                           f"and trade_date <= date(?, '+800 day') order by trade_date, volume_raw desc limit 1", par + [ex, ex]).fetchone()
        if pre and post and pre[1] > 0 and post[1] > 0:
            raw_ratio, off, pair = post[1] / pre[1], 0, (pre[0], post[0])
            pre_sym, pre_date = con.execute(f"select symbol, trade_date from market_data_lake_staging where {where} and trade_date = ? limit 1", par + [pre[0]]).fetchone()
            days = (pd.Timestamp(post[0]) - pd.Timestamp(pre[0])).days
            basis = f"across the gap: last close {pre[0]} vs first close {post[0]} ({days} calendar days)"
            if YAHOO_FROM <= post[0] and pre[0] <= YAHOO_TO:
                cs = canonical(con, isin, sym, ex)
                a = {d: c for d, c in con.execute("select trade_date, close_raw from market_data_lake_yahoo_archive where symbol=? and trade_date in (?,?)",
                                                 (cs, *pair))}
                if len(a) == 2:
                    yf = (a[pair[0]] / pre[1]) / (a[pair[1]] / post[1])
    tier, ev = classify(f, raw_ratio, yf)
    if pair and off:
        ev += f"; price step found {off:+d} sessions from the ex-date ({pair[1]})"
    if basis.startswith("across"):
        ev += f"; basis: {basis}"
    # the lake symbol that holds the PRE-ex-date prices (the history the event must adjust); the feed symbol is the company's CURRENT
    # symbol and can differ (8KMILES -> SECURKLOUD with a gap between the names)
    lake_sym = None
    if pre_sym:
        m = con.execute("select canonical_symbol from isin_symbol_map where symbol=? and first_date<=? and last_date>=? limit 1", (pre_sym, pre_date, pre_date)).fetchone()
        lake_sym = m[0] if m else pre_sym
    return {"lake_symbol": lake_sym, "factor_logged": f, "raw_ratio": raw_ratio, "raw_offset": off, "step_date": pair[1] if pair else None,
            "yahoo_factor": yf, "tier": tier, "evidence": ev, "evidence_basis": basis if raw_ratio is not None else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--raw", default=str(ROOT / "data/reference/nse_corporate_actions_raw.csv"))
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=120)
    ev = parse_events(Path(a.raw))
    px = ev[ev.factor.notna()]
    res = {}
    for (sym, ex), g in px.groupby(["symbol", "ex_date"]):
        res[(sym, ex)] = evidence_for(con, g)
    out = ev.copy()
    for k in ("lake_symbol", "factor_logged", "raw_ratio", "raw_offset", "step_date", "yahoo_factor", "tier", "evidence", "evidence_basis"):
        out[k] = [res.get((r.symbol, r.ex_date), {}).get(k) if r.action_type in ("SPLIT", "BONUS") else None for r in out.itertuples()]
    out["tier"] = out["tier"].fillna("NOT_PRICE_MOVING")
    nod = out.evidence.fillna("").str.contains("no price data")
    out["no_data_reason"] = np.select(
        [nod & (out.ex_date < "2013-01-04"), nod & (out.ex_date > "2026-09-30"), nod],
        ["before staging starts (2013-01-01)", "after the data window (2026-09-30)", "symbol had no EQ-series rows around the ex-date"], None)
    out["stored_action_type"] = np.where(out.tier == "UNSUPPORTED", "OTHER", out.action_type)
    out.to_csv(ROOT / "data/reference/corporate_actions_evidence.csv", index=False)
    pm = out[out.action_type.isin(["SPLIT", "BONUS"])]
    print("price-moving rows:", len(pm), "events:", pm.groupby(["symbol", "ex_date"]).ngroups)
    print(pm.groupby(["action_type", "tier"]).size().unstack(fill_value=0))
    print("by year x tier:\n", pm.assign(y=pm.ex_date.str[:4]).groupby(["y", "tier"]).size().unstack(fill_value=0))
    print("no price data, by reason:", pm.no_data_reason.value_counts())
    seen = pm[pm.no_data_reason.isna()]
    print("events with price data: tiers", seen.groupby("tier").size())
    return 0


if __name__ == "__main__":
    sys.exit(main())
