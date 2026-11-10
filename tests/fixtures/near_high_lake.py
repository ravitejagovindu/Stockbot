"""A file-backed 330-session synthetic lake for the near-52-week-high signal-count study (never touches finsight.db).

Every expected nearness can be computed independently from the generator's own ``base`` series (the ADJUSTED closes):
  UP1, UP2     rising with small deterministic noise (nearness close to 1.00);
  PULLBK       rising to session 299, then 3% below that peak;  DEEP  rising to 299, then 12% below it (not a candidate);
  EDGEOK       80 until 99, 100 on session 100, exactly 95.0 afterwards (nearness exactly 0.95: a candidate);  EDGELO  the same with 94.99 (0.9499: not a candidate);
  TIEA, TIEB   constant 100.0 (nearness exactly 1.00, a tie: ranked by symbol);
  SPLITCO      rising, a 1:5 split at session SPLIT_IDX (raw prices / 5 from then on, volume x 5, one SPLIT row in corporate_actions_log);
  GAP2         rising, no bars on sessions 290..291 (2 missing: still passes the gap guard);  GAP3  no bars on 290..292 (3 missing: dropped);
  LATECO       one bar on session 0, then absent until session 280 (fewer than 252 bars when it is eligible again);
  DEMCO        rising, a DEMERGER row in corporate_actions_log at DEMERGER_IDX (not adjusted by the engine);
  DN1          falling (never near its high).
Volumes are large enough that every name passes the shared 25 crore ADTV rule; all names trade on the lake's first day, so the F2 listing-age rule treats them as seasoned.
"""
from __future__ import annotations

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stockbot.data.db.connection import Base
from stockbot.data.db.models import CorporateActionsLog, MarketDataLake
from tests.fixtures import mini_lake

N = 330
SPLIT_IDX = 280
DEMERGER_IDX = 300
GAP2, GAP3 = range(290, 292), range(290, 293)
LATE_BACK = 280
PEAK = 299
DRIFTS = {"UP1": 0.0020, "UP2": 0.0015, "PULLBK": 0.0020, "DEEP": 0.0020, "SPLITCO": 0.0022, "GAP2": 0.0018, "GAP3": 0.0018, "LATECO": 0.0020, "DEMCO": 0.0016, "DN1": -0.0010}
STARTS = {"UP1": 100.0, "UP2": 120.0, "PULLBK": 140.0, "DEEP": 160.0, "SPLITCO": 150.0, "GAP2": 130.0, "GAP3": 135.0, "LATECO": 170.0, "DEMCO": 110.0, "DN1": 400.0}
CONTINUOUS = ("UP1", "UP2", "PULLBK", "DEEP", "EDGEOK", "EDGELO", "TIEA", "TIEB", "SPLITCO", "DEMCO", "DN1")      # a bar on every session


def base_series() -> dict:
    """symbol -> numpy array of adjusted closes (the 'truth' the study must reproduce)."""
    out = {}
    for k, sym in enumerate(sorted(DRIFTS)):
        rng = np.random.default_rng(2000 + k)
        z = rng.standard_normal(N)
        i = np.arange(N)
        out[sym] = STARTS[sym] * np.exp(DRIFTS[sym] * i) * (1.0 + 0.002 * z)
    for sym in ("PULLBK", "DEEP"):
        f = 0.97 if sym == "PULLBK" else 0.88
        out[sym][PEAK + 1:] = out[sym][PEAK] * f
    for sym, last in (("EDGEOK", 95.0), ("EDGELO", 94.99)):
        c = np.full(N, 80.0)
        c[100] = 100.0
        c[101:] = last
        out[sym] = c
    out["TIEA"] = np.full(N, 100.0)
    out["TIEB"] = np.full(N, 100.0)
    return out


def build(path):
    eng = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(eng)
    ds = mini_lake.sessions(N)
    base = base_series()
    with sessionmaker(bind=eng)() as s:
        for d in ds:
            s.add(MarketDataLake(symbol="NIFTY50_INDEX", trade_date=d, open_raw=20000.0, high_raw=20100.0, low_raw=19900.0, close_raw=20050.0, volume_raw=1_000_000, exchange="NSE"))
            s.add(MarketDataLake(symbol="INDIA_VIX", trade_date=d, open_raw=14.0, high_raw=14.5, low_raw=13.5, close_raw=14.0, volume_raw=0, exchange="NSE"))
        for sym, c in base.items():
            for i, d in enumerate(ds):
                if (sym == "GAP2" and i in GAP2) or (sym == "GAP3" and i in GAP3):
                    continue
                if sym == "LATECO" and 0 < i < LATE_BACK:
                    continue
                f = 0.2 if (sym == "SPLITCO" and i >= SPLIT_IDX) else 1.0
                vol = 30_000_000 if f != 1.0 else 6_000_000
                px = float(c[i]) * f
                s.add(MarketDataLake(symbol=sym, trade_date=d, open_raw=px * 0.999, high_raw=px * 1.01, low_raw=px * 0.99, close_raw=px, volume_raw=vol, exchange="NSE"))
        s.add(CorporateActionsLog(symbol="SPLITCO", ex_date=ds[SPLIT_IDX], action_type="SPLIT", ratio_numerator=1, ratio_denominator=5, source="test", evidence_tier="T1"))
        s.add(CorporateActionsLog(symbol="DEMCO", ex_date=ds[DEMERGER_IDX], action_type="DEMERGER", ratio_numerator=1, ratio_denominator=1, source="test", evidence_tier="T1"))
        s.commit()
    eng.dispose()
    return ds, base
