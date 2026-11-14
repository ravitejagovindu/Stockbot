"""In-memory as-of view: ``MemoryAsOfView`` answers exactly like ``AsOfView`` but reads market data from arrays loaded ONCE from the lake instead of one SQL query per call.

Only the data-fetch primitives are replaced (raw bars, corporate actions, the trading calendar, the symbols that traded on a day, first date and count of a symbol); every rule
on top of them is the code of ``AsOfView`` itself, inherited and unchanged: the bound ``trade_date <= as_of`` and ``FutureDataError``, the adjustment (``get_adjusted_series``),
ADTV (``compute_adtv``), listing age (``symbol_info``), the earnings methods (still SQL; they are per-candidate, not per-universe-member) and, above this module, eligibility.
The view cannot drift from the SQL view because it contains none of that logic.

Loading: ``market_data_lake`` (symbol, trade_date, open/high/low/close/volume raw; the table holds EQ-series rows and the two index series, see DATA_GUIDE section D) and
``corporate_actions_log`` are read once through the connection given (which comes from ``open_lake``, read-only), in chunks, into numpy arrays sorted by (symbol, date): about
270 MB for 5.6 million rows. Nothing is written anywhere, the lake file included. The snapshot is taken at the first view built on a connection and kept while that
connection is the one most recently used (a lake changed afterwards is not seen; the lake is frozen during a run). Selected by ``STOCKBOT_VIEW=memory`` (see ``AsOfView.__new__``) or by building this class.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from stockbot.data.asof import NIFTY, VIX, AsOfView, _d

_CHUNK = 500_000
_RAW_COLS = ["open_raw", "high_raw", "low_raw", "close_raw", "volume_raw"]


class _Tables:
    """The lake tables as arrays, sorted by (symbol, date). One instance per connection."""

    def __init__(self, conn):
        syms: list = []
        ords: list = []
        px: list = []                       # one (n, 4) float64 array per chunk
        vol: list = []
        code_of: dict = {}
        day_ord: dict = {}
        cur = conn.execute("select symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw from market_data_lake")
        while True:
            rows = cur.fetchmany(_CHUNK)
            if not rows:
                break
            c = np.empty(len(rows), dtype=np.int32)
            o = np.empty(len(rows), dtype=np.int32)
            for i, r in enumerate(rows):
                s = r[0]
                k = code_of.get(s)
                if k is None:
                    k = code_of[s] = len(code_of)
                c[i] = k
                t = r[1]
                v = day_ord.get(t)
                if v is None:
                    if len(str(t)) != 10:
                        raise ValueError(f"market_data_lake.trade_date is not a plain ISO date: {t!r}")
                    v = day_ord[t] = date.fromisoformat(t).toordinal()
                o[i] = v
            syms.append(c)
            ords.append(o)
            px.append(np.array([(float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows], dtype=np.float64))
            vol.append(np.fromiter((int(r[6]) for r in rows), dtype=np.int64, count=len(rows)))
            del rows
        names = sorted(code_of)                                                   # code-point order == SQLite BINARY order for the ASCII symbols of the lake
        rank = np.empty(len(code_of), dtype=np.int32)
        for new, s in enumerate(names):
            rank[code_of[s]] = new
        code = rank[np.concatenate(syms)] if syms else np.empty(0, np.int32)
        day = np.concatenate(ords) if ords else np.empty(0, np.int32)
        order = np.lexsort((day, code))
        self.code, self.day = code[order], day[order]
        self.px = (np.concatenate(px) if px else np.empty((0, 4)))[order]
        self.vol = (np.concatenate(vol) if vol else np.empty(0, np.int64))[order]
        del syms, ords, px, vol, code, day, order
        self.names = names
        self.span: dict = {}                                                      # symbol -> (lo, hi) rows
        if len(self.code):
            bounds = np.flatnonzero(np.diff(self.code)) + 1
            lo = np.concatenate(([0], bounds))
            hi = np.concatenate((bounds, [len(self.code)]))
            for k, a, b in zip(self.code[lo].tolist(), lo.tolist(), hi.tolist()):
                self.span[names[k]] = (a, b)
        lo_d = int(self.day.min()) if len(self.day) else 0
        hi_d = int(self.day.max()) if len(self.day) else 0
        self.date_base = lo_d
        self.dates = np.empty(hi_d - lo_d + 1, dtype=object)                      # ordinal -> the datetime.date object (shared, never rebuilt)
        for ordv in range(lo_d, hi_d + 1):
            self.dates[ordv - lo_d] = date.fromordinal(ordv)
        # who traded on each day: rows ordered by (day, symbol)
        o2 = np.lexsort((self.code, self.day))
        self.by_day_code = self.code[o2]
        self.by_day = self.day[o2]
        del o2
        self._day_cache: dict = {}
        nf = self.span.get(NIFTY)
        self.nifty = self.day[nf[0]:nf[1]] if nf else np.empty(0, np.int32)
        self.nifty_first = date.fromordinal(int(self.nifty[0])) if len(self.nifty) else None
        self._conn = conn
        self._actions = None

    @property
    def actions(self) -> dict:
        """Corporate actions per symbol, in the order the SQL view's query returns them. Loaded on first use (a lake without the table fails here, at the first call, as the SQL view does)."""
        if self._actions is None:
            acts: dict = {}
            for sym, ex, t, num, den in self._conn.execute("select symbol, ex_date, action_type, ratio_numerator, ratio_denominator from corporate_actions_log order by symbol, ex_date"):
                acts.setdefault(sym, []).append((str(ex), date.fromisoformat(str(ex)[:10]), t, num, den))
            self._actions = acts
        return self._actions

    def symbols_on(self, ordinal: int) -> list:
        got = self._day_cache.get(ordinal)
        if got is None:
            lo = int(np.searchsorted(self.by_day, ordinal, side="left"))
            hi = int(np.searchsorted(self.by_day, ordinal, side="right"))
            got = [self.names[k] for k in self.by_day_code[lo:hi].tolist()]
            if len(self._day_cache) > 64:
                self._day_cache.clear()
            self._day_cache[ordinal] = got
        return got


_SLOT: list = []        # [conn, tables]: the one snapshot kept. A sqlite3.Connection cannot be weakly referenced, so the slot holds the connection itself (this keeps it, and so its id, alive).


def _tables_for(conn) -> _Tables:
    if _SLOT and _SLOT[0] is conn:
        return _SLOT[1]
    tables = _Tables(conn)
    _SLOT[:] = [conn, tables]                                                    # a second connection replaces the snapshot (correct, only slower if two connections alternate)
    return tables


class MemoryAsOfView(AsOfView):
    def __init__(self, conn, as_of: date):
        super().__init__(conn, as_of)
        self._t = _tables_for(conn)
        self._as_of_ord = self._as_of.toordinal()

    # ------------------------------------------------------------------ bars
    def raw_bars(self, symbol: str, lookback: Optional[int] = 400, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        """Same contract as ``AsOfView.raw_bars`` (checks, bounds, ``lookback`` last bars, empty frame, dtypes, index of ``datetime.date``)."""
        self._check(end, "end")
        self._check(start, "start")
        hi = _d(end) if end is not None else self._as_of
        sp = self._t.span.get(symbol)
        rows = 0
        if sp is not None:
            a, b = sp
            days = self._t.day[a:b]
            j = int(np.searchsorted(days, hi.toordinal(), side="right"))
            i = int(np.searchsorted(days, _d(start).toordinal(), side="left")) if start is not None else 0
            if lookback:
                i = max(i, j - int(lookback))
            rows = max(j - i, 0)
        if not rows:
            return pd.DataFrame(columns=_RAW_COLS)
        px, vol = self._t.px[a + i:a + j], self._t.vol[a + i:a + j]
        idx = pd.Index(self._t.dates[days[i:j] - self._t.date_base], dtype=object, name="trade_date")
        return pd.DataFrame({"open_raw": px[:, 0].copy(), "high_raw": px[:, 1].copy(), "low_raw": px[:, 2].copy(), "close_raw": px[:, 3].copy(), "volume_raw": vol.copy()}, index=idx)

    # ----------------------------------------------------- actions, calendar
    def corporate_actions(self, symbol: str) -> list[dict]:
        lim = self._as_of.isoformat()
        return [{"ex_date": exd, "action_type": t, "ratio_numerator": num, "ratio_denominator": den}
                for ex, exd, t, num, den in self._t.actions.get(symbol, ()) if ex <= lim]

    def sessions(self, lookback: Optional[int] = None) -> list[date]:
        n = int(np.searchsorted(self._t.nifty, self._as_of_ord, side="right"))
        a = self._t.nifty[:n]
        if lookback:
            a = a[-int(lookback):]
        return [self._t.dates[o - self._t.date_base] for o in a.tolist()]

    # --------------------------------------------------------------- symbols
    def _symbols_on_as_of(self) -> list[str]:
        return self._t.symbols_on(self._as_of_ord)

    def _lake_first_date(self) -> Optional[date]:
        return self._t.nifty_first

    def _first_and_count(self, symbol: str):
        sp = self._t.span.get(symbol)
        if sp is None:
            return None, 0
        a, b = sp
        days = self._t.day[a:b]
        n = int(np.searchsorted(days, self._as_of_ord, side="right"))
        if n == 0:
            return None, 0
        return self._t.dates[int(days[0]) - self._t.date_base], n
