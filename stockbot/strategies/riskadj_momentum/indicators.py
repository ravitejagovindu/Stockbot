"""ATR for riskadj_momentum, shared by the strategy (initial stop) and its exit policy (trailing stop): the library's Wilder ATR over the symbol's last ``ATR_BARS`` adjusted bars.

``stockbot.data.indicators.atr`` is the Wilder ATR (true range = max(H-L, |H-prevC|, |L-prevC|), first bar H-L, ``rma`` smoothing seeded with the simple mean of the first
``period`` true ranges, then avg = (avg x (period-1) + TR) / period), so it is used as is; a hand-computed test pins it. Because the Wilder seed decays, the NUMBER of bars matters
a little: both callers use the same fixed ``ATR_BARS`` (252) bars ending at the as-of session, so the signal's ATR and every later session's ATR are computed the same way.
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from stockbot.data.indicators import atr as _atr

ATR_BARS = 252


def atr_last(bars: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Wilder ATR of the last bar of ``bars`` (adjusted columns high_adj, low_adj, close_adj; oldest first), using at most the last ``ATR_BARS`` bars. None if it cannot be computed."""
    b = bars.iloc[-ATR_BARS:]
    if len(b) < period + 1:
        return None
    v = float(_atr(b["high_adj"].astype(float), b["low_adj"].astype(float), b["close_adj"].astype(float), period).iloc[-1])
    return v if math.isfinite(v) else None
