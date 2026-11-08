"""The point-in-time ("as-of") view of the lake: the ONLY way code above ``data`` reads market data.

``AsOfView(conn, as_of)`` answers questions as they could have been answered at the close of ``as_of``:
  - every query is bounded by ``trade_date <= as_of`` in SQL; asking for a bar after ``as_of`` (an explicit ``end`` or ``start`` beyond it) raises
    ``FutureDataError`` - there is no way to read the future through this object;
  - prices are adjusted inside the view with the existing ``get_adjusted_series`` (split/bonus actions with ex_date <= as_of only);
  - corporate actions returned are those known by ``as_of`` (ex_date <= as_of);
  - raw close / raw volume / traded value are exposed separately from adjusted prices (liquidity uses raw, never adjusted);
  - the connection is private; callers get frames and small value objects, never a session or cursor.
The connection passed in should come from ``stockbot.data.lake.open_lake`` (read-only); the view itself only issues SELECTs.
Not exposed: ``shares_outstanding`` / market cap (single current snapshot, KI-001; the market-cap gate is parked).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from stockbot.config.paths import repo_root
from stockbot.data.adjustments import compute_adtv, get_adjusted_series

NIFTY, VIX = "NIFTY50_INDEX", "INDIA_VIX"
DEFAULT_LOOKBACK = 400


class FutureDataError(ValueError):
    """A request would include a bar after the view's as-of date."""


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    first_date: Optional[date]       # first bar on or before as_of
    n_sessions: int                  # bars on or before as_of
    is_fund_or_etf: bool


@lru_cache(maxsize=1)
def _fund_symbols() -> frozenset:
    p = repo_root() / "data" / "reference" / "fund_etf_symbols.csv"
    if not p.exists():
        return frozenset()
    with open(p, newline="", encoding="utf-8") as f:
        return frozenset(r["symbol"].strip().upper() for r in csv.DictReader(f) if r.get("symbol"))


def _d(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


class AsOfView:
    def __init__(self, conn, as_of: date):
        self._conn = conn
        self._as_of = _d(as_of)

    @property
    def as_of(self) -> date:
        return self._as_of

    def _check(self, d: Optional[date], what: str) -> None:
        if d is not None and _d(d) > self._as_of:
            raise FutureDataError(f"{what} {d} is after the as-of date {self._as_of}")

    # ------------------------------------------------------------------ bars
    def raw_bars(self, symbol: str, lookback: Optional[int] = DEFAULT_LOOKBACK, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        """Raw OHLCV (open_raw..volume_raw), index = datetime.date ascending, the last ``lookback`` bars in [start, end]; ``end`` defaults to as_of."""
        self._check(end, "end")
        self._check(start, "start")
        hi = _d(end) if end is not None else self._as_of
        sql = ("select trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw from market_data_lake "
               "where symbol=? and trade_date<=?")
        args: list = [symbol, hi.isoformat()]
        if start is not None:
            sql += " and trade_date>=?"
            args.append(_d(start).isoformat())
        sql += " order by trade_date desc"
        if lookback:
            sql += " limit ?"
            args.append(int(lookback))
        rows = self._conn.execute(sql, args).fetchall()
        if not rows:
            return pd.DataFrame(columns=["open_raw", "high_raw", "low_raw", "close_raw", "volume_raw"])
        df = pd.DataFrame([{"trade_date": date.fromisoformat(str(r[0])[:10]), "open_raw": float(r[1]), "high_raw": float(r[2]), "low_raw": float(r[3]),
                            "close_raw": float(r[4]), "volume_raw": int(r[5])} for r in reversed(rows)]).set_index("trade_date")
        return df

    def adjusted_bars(self, symbol: str, lookback: Optional[int] = DEFAULT_LOOKBACK, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        """Split/bonus-adjusted prices (open_adj..close_adj) in the price basis in force on as_of; volume is never adjusted (use raw_bars)."""
        raw = self.raw_bars(symbol, lookback, start, end)
        if raw.empty:
            return pd.DataFrame(columns=["open_adj", "high_adj", "low_adj", "close_adj"])
        return get_adjusted_series(raw, self.corporate_actions(symbol), as_of_date=self._as_of)

    def raw_close(self, symbol: str, lookback: Optional[int] = DEFAULT_LOOKBACK) -> pd.Series:
        return self.raw_bars(symbol, lookback)["close_raw"]

    def traded_value(self, symbol: str, lookback: Optional[int] = DEFAULT_LOOKBACK) -> pd.Series:
        """Raw close x raw volume per session (rupees)."""
        b = self.raw_bars(symbol, lookback)
        return b["close_raw"] * b["volume_raw"]

    def adtv(self, symbol: str, period: int = 20) -> Optional[float]:
        """Latest ADTV (rupees) over ``period`` sessions from raw prices; None if fewer than ``period`` bars."""
        b = self.raw_bars(symbol, period)
        if len(b) < period:
            return None
        return float(compute_adtv(b["close_raw"], b["volume_raw"], period).iloc[-1])

    def index_bars(self, symbol: str = NIFTY, lookback: Optional[int] = DEFAULT_LOOKBACK) -> pd.DataFrame:
        """Index / VIX series (NIFTY50_INDEX, INDIA_VIX) as stored (raw OHLC)."""
        if symbol not in (NIFTY, VIX):
            raise ValueError(f"not an index series: {symbol}")
        return self.raw_bars(symbol, lookback)

    # ----------------------------------------------------- actions, calendar
    def corporate_actions(self, symbol: str) -> list[dict]:
        """Actions in corporate_actions_log known by as_of (ex_date <= as_of), oldest first."""
        rows = self._conn.execute(
            "select ex_date, action_type, ratio_numerator, ratio_denominator from corporate_actions_log where symbol=? and ex_date<=? order by ex_date",
            (symbol, self._as_of.isoformat())).fetchall()
        return [{"ex_date": date.fromisoformat(str(r[0])[:10]), "action_type": r[1], "ratio_numerator": r[2], "ratio_denominator": r[3]} for r in rows]

    def sessions(self, lookback: Optional[int] = None) -> list[date]:
        """Trading calendar up to and including as_of (dates of the Nifty series), ascending."""
        sql = "select trade_date from market_data_lake where symbol=? and trade_date<=? order by trade_date desc"
        args: list = [NIFTY, self._as_of.isoformat()]
        if lookback:
            sql += " limit ?"
            args.append(int(lookback))
        return [date.fromisoformat(str(r[0])[:10]) for r in reversed(self._conn.execute(sql, args).fetchall())]

    # --------------------------------------------------------------- symbols
    def symbols_trading(self) -> list[str]:
        """Symbols with a bar on the as-of date itself (index series excluded)."""
        rows = self._conn.execute("select symbol from market_data_lake where trade_date=? order by symbol", (self._as_of.isoformat(),)).fetchall()
        return [r[0] for r in rows if r[0] not in (NIFTY, VIX)]

    def symbol_info(self, symbol: str) -> SymbolInfo:
        r = self._conn.execute("select min(trade_date), count(*) from market_data_lake where symbol=? and trade_date<=?", (symbol, self._as_of.isoformat())).fetchone()
        first = date.fromisoformat(str(r[0])[:10]) if r and r[0] else None
        return SymbolInfo(symbol, first, int(r[1] or 0), symbol.strip().upper() in _fund_symbols())
