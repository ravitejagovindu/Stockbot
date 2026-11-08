"""Phase 3 equivalence tests on the REAL lake (STOCKBOT_DATA_TESTS=1): the as-of view must give the same numbers as the current engine paths.

  1. 120 (symbol, eval_date) samples (40 symbols x 3 dates, rng seed 7, as in scripts/f2_engine_scan.py): view.raw_bars / adjusted_bars equal
     build_candidate_dicts' raw_ohlcv / adjusted_ohlcv (0 mismatches required).
  2. The 57 verification rows (data/reference/verified_corporate_actions.csv) go through the view and PASS the same checks as
     scripts/f2_verify_engine_path.verify_row; the engine factor on the bar before the ex-date equals the original engine path's factor.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

DB = Path(os.environ.get("STOCKBOT_DB") or Path(__file__).resolve().parents[2] / "finsight.db")
RUN = os.environ.get("STOCKBOT_DATA_TESTS") == "1"
if RUN and not DB.exists():
    raise RuntimeError(f"STOCKBOT_DATA_TESTS=1 but the database {DB} does not exist")
pytestmark = pytest.mark.skipif(not RUN, reason="needs STOCKBOT_DATA_TESTS=1 and the real database")

V = Path(__file__).resolve().parents[2] / "data/reference/verified_corporate_actions.csv"
ROWS = list(pd.read_csv(V).itertuples()) if V.exists() else []


@pytest.fixture(scope="module")
def conn():
    from stockbot.data.lake import open_lake
    c = open_lake(DB)
    yield c
    c.close()


@pytest.fixture(scope="module")
def orm_session():
    from scripts.f2_engine_scan import session_for
    return session_for(str(DB))


def test_120_samples_view_equals_build_candidate_dicts(conn, orm_session):
    from engine_core.candidate_builder import build_candidate_dicts
    from stockbot.data.asof import AsOfView
    cfg = {"data": {"resistance_lookback_days": 252}}
    syms = [r[0] for r in conn.execute("select symbol from market_data_lake group by symbol having count(*) >= 300 order by symbol")]
    syms = [s for s in syms if s not in ("NIFTY50_INDEX", "INDIA_VIX")]
    rng = np.random.default_rng(7)
    sample = list(rng.choice(syms, size=40, replace=False))
    checked = mism = 0
    for sym in sample:
        dates = [date.fromisoformat(r[0]) for r in conn.execute("select trade_date from market_data_lake where symbol=? order by trade_date", (sym,))]
        for k in rng.choice(len(dates), size=3, replace=False):
            d = dates[int(k)]
            cand = build_candidate_dicts(orm_session, cfg, [sym], d)
            if not cand:
                continue
            v = AsOfView(conn, d)
            lb = len(cand[0]["raw_ohlcv"])
            checked += 1
            try:
                pd.testing.assert_frame_equal(v.raw_bars(sym, lb), cand[0]["raw_ohlcv"], check_exact=True)
                pd.testing.assert_frame_equal(v.adjusted_bars(sym, lb), cand[0]["adjusted_ohlcv"], rtol=1e-12, atol=0)
            except AssertionError:
                mism += 1
    print(f"as-of view vs build_candidate_dicts: {checked} samples, {mism} mismatches")
    assert checked == 120 and mism == 0


@pytest.mark.parametrize("r", ROWS, ids=[f"{r.symbol}-{r.ex_date}-{r.action_type}" for r in ROWS])
def test_verification_row_through_the_view(conn, orm_session, r):
    from sqlalchemy import or_, select
    from data.db.models import CorporateActionsLog
    from scripts.f2_engine_scan import engine_frames
    from stockbot.data.adjustments import action_factor
    from stockbot.data.asof import AsOfView
    v = pd.read_csv(V)
    same = v[(v.symbol == r.symbol) & (v.ex_date == r.ex_date) & v.action_type.isin(["SPLIT", "BONUS"])]
    expected = float(np.prod(same["expected_factor"])) if r.action_type in ("SPLIT", "BONUS") else 1.0
    ex = date.fromisoformat(r.ex_date)
    logs = orm_session.execute(select(CorporateActionsLog).where(CorporateActionsLog.ex_date == ex)
                               .where(or_(CorporateActionsLog.symbol == r.symbol, CorporateActionsLog.notes.like(f"%feed_symbol={r.symbol};%")))).scalars().all()
    mine = [c for c in logs if c.action_type == r.action_type]
    assert mine, "no log row of that type for this feed symbol and ex-date"
    lake_sym = mine[0].symbol
    nxt = conn.execute("select min(trade_date) from market_data_lake where symbol=? and trade_date>=?", (lake_sym, ex.isoformat())).fetchone()[0]
    assert nxt, f"no lake rows on/after the ex-date for {lake_sym}"
    view = AsOfView(conn, date.fromisoformat(nxt))                   # the first session on/after the ex-date: nothing later is needed
    raw = view.raw_bars(lake_sym, None, start=ex - timedelta(days=60))
    adj = view.adjusted_bars(lake_sym, None, start=ex - timedelta(days=60))
    before = [d for d in raw.index if d < ex]
    after = [d for d in raw.index if d >= ex]
    assert before and after, "no bars on both sides of the ex-date in the lake"
    p, o = before[-1], after[0]
    f_view = float(adj.loc[p, "close_adj"] / raw.loc[p, "close_raw"])
    # the same number from the original engine path (as_of = the ex-date)
    raw0, adj0 = engine_frames(orm_session, lake_sym, as_of=ex, lo=ex - timedelta(days=60), hi=ex + timedelta(days=30))
    f_orig = float(adj0.loc[p, "close_adj"] / raw0.loc[p, "close_raw"])
    assert abs(f_view / f_orig - 1) < 1e-12, (f_view, f_orig)
    if r.action_type in ("SPLIT", "BONUS"):
        prod = float(np.prod([action_factor(a) for a in view.corporate_actions(lake_sym) if a["ex_date"] == ex and a["action_type"] in ("SPLIT", "BONUS")]))
        assert abs(prod / expected - 1) < 0.01 and abs(f_view / expected - 1) < 0.01
        assert abs(float(adj.loc[o, "close_adj"] / adj.loc[p, "close_adj"]) - 1) < 0.25
    else:
        assert abs(f_view - 1.0) < 1e-9 and not any(a["action_type"] in ("SPLIT", "BONUS") and a["ex_date"] == ex for a in view.corporate_actions(lake_sym))
