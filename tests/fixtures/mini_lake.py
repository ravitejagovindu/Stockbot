"""A small deterministic lake for tests that must not touch finsight.db (F10).

330 weekday sessions from 2019-01-01.  NIFTY50_INDEX rises 4 points a day (always above its SMA200), VIX is flat at 14.
FIXCO (500M shares, 3M shares/day) rises 0.25 a day to a 25-session consolidation (closes 172-173), breaks out on session 300
(close 176 > the prior 20-session high 173), and a one-day spike high of 215 on session 150 is the 252-session resistance target.
Session 301 opens at 177; session 302 gaps down to 160, through the stop.
"""
from __future__ import annotations

from datetime import date, timedelta

from stockbot.data.db.models import MarketDataLake, SharesOutstanding

N_SESSIONS = 330
BREAKOUT = 300          # signal session (close T)
ENTRY = 301             # fill session (open T+1)
CRASH = 302             # gap-down session


def sessions(n: int = N_SESSIONS, start: date = date(2019, 1, 1)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def fixco_bars(i: int) -> tuple[float, float, float, float]:
    """(open, high, low, close) of FIXCO on session i."""
    if i < 275:
        c = 100.0 + 0.25 * i
        o, h, l = c - 0.5, c + 1.0, c - 1.0
        if i == 150:
            h = 215.0                                     # spike high: the resistance target
        return (o, h, l, c)
    if i < BREAKOUT:
        return (172.0, 173.0, 163.0, 172.0 + (0.5 if i % 2 else 0.0))
    if i == BREAKOUT:
        return (173.0, 177.0, 172.5, 176.0)
    if i == ENTRY:
        return (177.0, 178.0, 176.0, 177.5)
    if i == CRASH:
        return (160.0, 161.0, 158.0, 159.0)
    return (159.0, 160.0, 157.0, 158.0)


def build(session) -> list[date]:
    ds = sessions()
    for i, d in enumerate(ds):
        session.add(MarketDataLake(symbol="NIFTY50_INDEX", trade_date=d, open_raw=10000.0 + 4 * i, high_raw=10010.0 + 4 * i,
                                   low_raw=9990.0 + 4 * i, close_raw=10000.0 + 4 * i, volume_raw=1_000_000, exchange="NSE"))
        session.add(MarketDataLake(symbol="INDIA_VIX", trade_date=d, open_raw=14.0, high_raw=14.5, low_raw=13.5, close_raw=14.0,
                                   volume_raw=0, exchange="NSE"))
        o, h, l, c = fixco_bars(i)
        session.add(MarketDataLake(symbol="FIXCO", trade_date=d, open_raw=o, high_raw=h, low_raw=l, close_raw=c,
                                   volume_raw=3_000_000, exchange="NSE"))
    session.add(SharesOutstanding(symbol="FIXCO", effective_date=ds[0], shares_count=500_000_000))
    session.flush()
    return ds
