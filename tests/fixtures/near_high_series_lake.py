"""Build a file-backed synthetic lake from explicit ADJUSTED close series (the 'truth'), for the near_52w_high strategy tests. Never touches finsight.db.

``build(path, series, skip=..., volume=..., splits=...)``: every symbol gets a bar on every session except the indexes in ``skip[symbol]``; raw prices are the series times the split
factor from the ex-index on (a SPLIT row is written), so the as-of view must adjust them. Open = 0.999 x close, high = 1.01 x close, low = 0.99 x close. All names trade on the
lake's first day (the F2 listing-age rule then treats them as seasoned) and are liquid enough for the shared ADTV rule at the default volume.
"""
from __future__ import annotations

from typing import Mapping, Optional

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stockbot.data.db.connection import Base
from stockbot.data.db.models import CorporateActionsLog, MarketDataLake
from tests.fixtures import mini_lake

N = 330
FIRST = 251                       # index of the 252nd session: the first session a name with a bar on every session has 252 bars
DEFAULT_VOLUME = 6_000_000


def rise(start: float, daily: float, n: int = N) -> np.ndarray:
    return start * (1.0 + daily) ** np.arange(n)


def build(path, series: Mapping[str, np.ndarray], *, skip: Optional[Mapping[str, set]] = None, volume: Optional[Mapping[str, int]] = None,
          splits: Optional[Mapping[str, tuple]] = None, n: int = N):
    """Returns the session dates. ``splits``: symbol -> (ex_index, numerator, denominator)."""
    skip, volume, splits = skip or {}, volume or {}, splits or {}
    eng = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(eng)
    ds = mini_lake.sessions(n)
    with sessionmaker(bind=eng)() as s:
        for d in ds:
            s.add(MarketDataLake(symbol="NIFTY50_INDEX", trade_date=d, open_raw=20000.0, high_raw=20100.0, low_raw=19900.0, close_raw=20050.0, volume_raw=1_000_000, exchange="NSE"))
            s.add(MarketDataLake(symbol="INDIA_VIX", trade_date=d, open_raw=14.0, high_raw=14.5, low_raw=13.5, close_raw=14.0, volume_raw=0, exchange="NSE"))
        for sym, c in series.items():
            ex = splits.get(sym)
            for i, d in enumerate(ds):
                if i in skip.get(sym, ()):
                    continue
                f = (ex[1] / ex[2]) if (ex and i >= ex[0]) else 1.0
                vol = int(volume.get(sym, DEFAULT_VOLUME) / f)
                px = float(c[i]) * f
                s.add(MarketDataLake(symbol=sym, trade_date=d, open_raw=px * 0.999, high_raw=px * 1.01, low_raw=px * 0.99, close_raw=px, volume_raw=vol, exchange="NSE"))
            if ex:
                s.add(CorporateActionsLog(symbol=sym, ex_date=ds[ex[0]], action_type="SPLIT", ratio_numerator=ex[1], ratio_denominator=ex[2], source="test", evidence_tier="T1"))
        s.commit()
    eng.dispose()
    return ds
