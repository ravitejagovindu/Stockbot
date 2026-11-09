"""A file-backed 300-session synthetic lake for the momentum signal-count study (never touches finsight.db).

Smooth exponential trends (small deterministic noise) so every expected score can be computed independently from the generator's own ``base`` series:
  UP1..UP5   rising at different drifts (trend passes, scores strictly ordered);   DN1, DN2  falling (trend fails);
  SPLITCO    rising, a 1:5 split at session SPLIT_IDX (raw prices / 5 from then on, volume x 5, one SPLIT row in corporate_actions_log);
  GAPCO      rising, no bars on sessions 200..209 (a 10-session gap);
  LATECO     one bar on session 0, then absent until session 240 (EQ-only re-entry: it has fewer than 200 bars when it is eligible again).
Volumes are large enough that every name passes the shared 25 crore ADTV rule; all names trade on the lake's first day, so the F2 listing-age rule treats them as seasoned.
"""
from __future__ import annotations

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stockbot.data.db.connection import Base
from stockbot.data.db.models import CorporateActionsLog, MarketDataLake
from tests.fixtures import mini_lake

N = 300
SPLIT_IDX = 220
GAP = range(200, 210)
LATE_BACK = 240
DRIFTS = {"UP1": 0.0030, "UP2": 0.0025, "UP3": 0.0020, "UP4": 0.0016, "UP5": 0.0012, "SPLITCO": 0.0022, "GAPCO": 0.0018, "LATECO": 0.0020, "DN1": -0.0010, "DN2": -0.0006}
STARTS = {"UP1": 100.0, "UP2": 120.0, "UP3": 140.0, "UP4": 160.0, "UP5": 180.0, "SPLITCO": 150.0, "GAPCO": 130.0, "LATECO": 170.0, "DN1": 400.0, "DN2": 350.0}


def base_series() -> dict:
    """symbol -> numpy array of adjusted closes (the 'truth' the study must reproduce)."""
    out = {}
    for k, sym in enumerate(sorted(DRIFTS)):
        rng = np.random.default_rng(1000 + k)
        z = rng.standard_normal(N)
        i = np.arange(N)
        out[sym] = STARTS[sym] * np.exp(DRIFTS[sym] * i) * (1.0 + 0.002 * z)
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
                if sym == "GAPCO" and i in GAP:
                    continue
                if sym == "LATECO" and 0 < i < LATE_BACK:
                    continue
                f = 0.2 if (sym == "SPLITCO" and i >= SPLIT_IDX) else 1.0
                vol = 30_000_000 if f != 1.0 else 6_000_000
                px = float(c[i]) * f
                s.add(MarketDataLake(symbol=sym, trade_date=d, open_raw=px * 0.999, high_raw=px * 1.01, low_raw=px * 0.99, close_raw=px, volume_raw=vol, exchange="NSE"))
        s.add(CorporateActionsLog(symbol="SPLITCO", ex_date=ds[SPLIT_IDX], action_type="SPLIT", ratio_numerator=1, ratio_denominator=5, source="test", evidence_tier="T1"))
        s.commit()
    eng.dispose()
    return ds, base
