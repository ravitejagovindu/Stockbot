"""stockbot/data_checks/f2_engine_scan.py — post-adjustment scan of large moves through the ENGINE's real adjustment code path.

Reads market_data_lake and corporate_actions_log with the ORM models and adjusts with ``stockbot.data.adjustments.get_adjusted_series``
exactly as ``engine_core.candidate_builder.build_candidate_dicts`` does (same query shape, same dict fields, same function).
An equivalence check runs ``build_candidate_dicts`` itself on sample symbols and compares its adjusted frame with the scan's.
Counts |adjusted close-to-close move| > 40% on ADTV-eligible equity names (raw price >= Rs5), 2013-01-01..2026-09-30.
Read-only.  Output: docs/data_audit/engine_scan_<tag>.md (+ csv)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
from stockbot.data.db.models import CorporateActionsLog, MarketDataLake       # noqa: E402
from stockbot.data.adjustments import get_adjusted_series              # noqa: E402
from engine_core.candidate_builder import build_candidate_dicts      # noqa: E402

OUT = ROOT / "docs" / "data_audit"
THR, MIN_PX, AS_OF = 0.40, 5.0, date(2026, 9, 30)


def session_for(db: str) -> Session:
    eng = create_engine(f"sqlite:///file:{Path(db).as_posix()}?mode=ro&uri=true", connect_args={"check_same_thread": False})
    return Session(eng)


def engine_frames(session: Session, sym: str, as_of: date, lo: date | None = None, hi: date | None = None):
    """(raw frame, adjusted frame) for one lake symbol, built the way candidate_builder builds them."""
    q = select(MarketDataLake.trade_date, MarketDataLake.open_raw, MarketDataLake.high_raw, MarketDataLake.low_raw,
               MarketDataLake.close_raw, MarketDataLake.volume_raw).where(MarketDataLake.symbol == sym)
    if lo:
        q = q.where(MarketDataLake.trade_date >= lo)
    if hi:
        q = q.where(MarketDataLake.trade_date <= hi)
    rows = session.execute(q.order_by(MarketDataLake.trade_date)).all()
    if not rows:
        return None, None
    raw = pd.DataFrame([{"trade_date": r.trade_date, "open_raw": float(r.open_raw), "high_raw": float(r.high_raw), "low_raw": float(r.low_raw),
                         "close_raw": float(r.close_raw), "volume_raw": int(r.volume_raw)} for r in rows]).set_index("trade_date")
    corp = [{"ex_date": c.ex_date, "action_type": c.action_type, "ratio_numerator": c.ratio_numerator, "ratio_denominator": c.ratio_denominator}
            for c in session.execute(select(CorporateActionsLog).where(CorporateActionsLog.symbol == sym)
                                     .order_by(CorporateActionsLog.ex_date)).scalars().all()]
    return raw, get_adjusted_series(raw, corp, as_of_date=as_of)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--tag", default="real")
    a = ap.parse_args()
    s = session_for(a.db)
    el = pd.read_csv(OUT / "eligible_symbols.csv")
    funds = set(el[el["eligible"] & el["is_fund_or_etf"]]["symbol"])
    elig = set(el[el["eligible"]]["symbol"]) - funds
    imap = pd.read_sql_query("select isin, symbol, canonical_symbol from isin_symbol_map", s.get_bind())
    syms = sorted(set(imap[imap["symbol"].isin(elig)]["canonical_symbol"]) | {x for x in elig if x not in set(imap["symbol"])})
    ua = pd.read_csv(ROOT / "data/reference/unadjusted_events.csv")
    ua_dates = ua.groupby("lake_symbol")["date"].apply(list).to_dict()
    raw_n = adj_n = fixed = created = 0
    resid = []
    lo, hi = date(2013, 1, 1), AS_OF
    frames = {}
    for sym in syms:
        raw, adj = engine_frames(s, sym, AS_OF, lo, hi)
        if raw is None or len(raw) < 2:
            continue
        r_raw = raw["close_raw"] / raw["close_raw"].shift(1)
        r_adj = adj["close_adj"] / adj["close_adj"].shift(1)
        ok_px = np.minimum(raw["close_raw"], raw["close_raw"].shift(1)) >= MIN_PX
        big_raw, big_adj = ((r_raw - 1).abs() > THR) & ok_px, ((r_adj - 1).abs() > THR) & ok_px
        raw_n += int(big_raw.sum()); adj_n += int(big_adj.sum())
        fixed += int((big_raw & ~big_adj).sum()); created += int((~big_raw & big_adj).sum())
        idx = list(raw.index)
        for j in np.flatnonzero(big_adj.values):
            d, pd_ = idx[j], idx[j - 1]
            gap = (d - pd_).days
            near = any(abs((pd.Timestamp(d) - pd.Timestamp(x)).days) <= 30 for x in ua_dates.get(sym, []))
            resid.append((sym, str(d), round(float(r_adj.iloc[j] - 1), 3), round(float(r_raw.iloc[j] - 1), 3), gap,
                          "after_gap_in_EQ_series" if gap > 30 else ("near_unadjusted_event" if near else "residual_no_explanation"), bool(big_raw.iloc[j])))
        frames[sym] = (len(raw))
    rdf = pd.DataFrame(resid, columns=["symbol", "date", "adjusted_move", "raw_move", "gap_days", "category", "was_big_before_adjustment"])
    rdf.to_csv(OUT / f"engine_scan_{a.tag}.csv", index=False)

    # equivalence with build_candidate_dicts (the real candidate path) on sample symbols / dates
    cfg = {"data": {"resistance_lookback_days": 252}}
    mism = checked = 0
    rng = np.random.default_rng(7)
    sample = list(rng.choice(list(frames), size=min(40, len(frames)), replace=False))
    for sym in sample:
        raw_all, _ = engine_frames(s, sym, AS_OF, lo, hi)
        idx = list(raw_all.index)
        for ev in rng.choice(len(idx), size=3, replace=False):
            eval_d = idx[int(ev)]
            cand = build_candidate_dicts(s, cfg, [sym], eval_d)
            if not cand:
                continue
            adj_c = cand[0]["adjusted_ohlcv"]
            _, adj_scan = engine_frames(s, sym, eval_d, lo, eval_d)
            sub = adj_scan.loc[adj_c.index]
            checked += 1
            if not np.allclose(sub["close_adj"].values, adj_c["close_adj"].values, rtol=1e-12):
                mism += 1
    lines = [f"# Engine-path scan ({a.tag})\n", f"Database: `{a.db}`.  Adjusted with `stockbot.data.adjustments.get_adjusted_series` from `corporate_actions_log` rows keyed by lake symbol.\n",
             f"Names scanned: {len(frames)}.\n", "```", f"large moves before adjustment : {raw_n}", f"large moves after adjustment  : {adj_n}",
             f"  removed by adjusting        : {fixed}", f"  created by adjusting        : {created}", "```\n", "Remaining by category:\n", "```",
             rdf.groupby("category").size().to_string(), "```\n",
             f"Equivalence with `build_candidate_dicts` (the candidate path itself): {checked} (symbol, eval_date) samples, {mism} mismatches.\n"]
    (OUT / f"engine_scan_{a.tag}.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if mism == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
