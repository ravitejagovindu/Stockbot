"""A 25-day synthetic lake: index + VIX + the stock SYNTH (entry fills at 102 on index 10, gap-down stop-out on index 17), optionally with a split / bonus on index 13.

Data only (no configuration): used with the frozen legacy results in tests/golden."""
from __future__ import annotations

from datetime import date, timedelta

from stockbot.data.db.models import CorporateActionsLog, MarketDataLake, SharesOutstanding

D0 = date(2024, 1, 1)
DATES = [D0 + timedelta(days=i) for i in range(25)]
PRICES = [
    (95.0, 100.0, 93.0, 96.0), (96.0, 135.0, 94.0, 97.0), (97.0, 100.0, 95.0, 98.0),
    (98.0, 100.0, 96.0, 99.0), (99.0, 100.0, 97.0, 100.0), (99.0, 101.0, 97.0, 100.0),
    (98.0, 101.0, 96.0, 99.0), (99.0, 101.0, 97.0, 100.0), (100.0, 102.0, 98.0, 101.0),
    (101.0, 102.0, 99.0, 102.0), (102.0, 107.0, 101.0, 106.0), (106.0, 110.0, 105.0, 109.0),
    (109.0, 112.0, 108.0, 111.0), (111.0, 114.0, 110.0, 113.0), (113.0, 116.0, 112.0, 115.0),
    (115.0, 117.0, 114.0, 116.0), (116.0, 118.0, 115.0, 117.0), (94.0, 95.0, 90.0, 91.0),
]
EX_IDX = 13


def build(session, action=None, ex_idx=EX_IDX, factor=1.0):
    for d in DATES:
        session.add(MarketDataLake(symbol="NIFTY50_INDEX", trade_date=d, open_raw=22000.0, high_raw=22100.0, low_raw=21900.0, close_raw=22050.0, volume_raw=1000000, exchange="NSE"))
        session.add(MarketDataLake(symbol="INDIA_VIX", trade_date=d, open_raw=14.0, high_raw=14.5, low_raw=13.5, close_raw=14.0, volume_raw=0, exchange="NSE"))
    session.add(SharesOutstanding(symbol="SYNTH", effective_date=DATES[0], shares_count=500_000_000))
    for i, (o, h, l, c) in enumerate(PRICES):
        f = factor if (action is not None and i >= ex_idx) else 1.0
        session.add(MarketDataLake(symbol="SYNTH", trade_date=DATES[i], open_raw=o * f, high_raw=h * f, low_raw=l * f, close_raw=c * f, volume_raw=5_000_000, exchange="NSE"))
    if action is not None:
        session.add(CorporateActionsLog(symbol="SYNTH", ex_date=DATES[ex_idx], action_type=action[0], ratio_numerator=action[1], ratio_denominator=action[2]))
    session.flush()
