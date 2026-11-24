"""Test worlds for the BFF: a temporary ``live_state.db``, a temporary lake and a tickets folder that mirror each of the contract's example scenarios.

Nothing here opens the real state or the real lake: every file lives under the ``tmp_path`` the caller passes in.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from bff.config import Settings
from stockbot.engine.apply import apply_decisions
from stockbot.engine.types import Blocked, ClosedTrade, Decisions, Fill, Flag, Position, PositionUpdate, State, Ticket, to_plain

IST = timezone(timedelta(hours=5, minutes=30))
START_DATE = date(2026, 11, 16)
SCENARIOS = ("empty", "signal_day", "positions", "trades", "deep_drawdown", "stale")
SID = "momentum_calm"

_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE journal (seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, session TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE (kind, key));
CREATE TABLE snapshot (id INTEGER PRIMARY KEY CHECK (id = 1), as_of TEXT, state TEXT NOT NULL);
"""


def weekdays(a: date, b: date) -> List[date]:
    out, d = [], a
    while d <= b:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@dataclass
class World:
    scenario: str
    settings: Settings
    now: datetime               # the "current time" the API should use (IST)
    root: Path
    data_as_of: date
    last_decisions: Decisions


# ------------------------------------------------------------------------------------------------------------------------------ trade tables (same numbers as the example files)
TRADES_ROWS = [("M&M", 70, 9, -1700), ("HINDALCO", 63, 33, 1600), ("ASIANPAINT", 57, 12, -1900), ("TATASTEEL", 50, 7, -2200), ("NTPC", 44, 29, 5100), ("AXISBANK", 37, 10, -1800),
               ("CIPLA", 31, 27, 2800), ("HCLTECH", 24, 5, -2300), ("ONGC", 19, 8, -2000), ("TITAN", 14, 31, 6200), ("BAJFINANCE", 9, 6, -2100), ("WIPRO", 4, 22, 3900)]
DEEP_P = [14000, 9500, -2000, 11000, -2100, 8200, -1900, 12500, -2200, 13000, -6500, -3000, -7200, -4100, 1800, -9500, -5800, -8300, 2400, -11000, -6900, -9200, -8600, -8600, 3900]
DEEP_SYMS = ["RELIANCE", "TCS", "ITC", "HDFCBANK", "INFY", "LT", "SBIN", "MARUTI", "TITAN", "NTPC", "ONGC", "CIPLA", "AXISBANK", "WIPRO", "HINDALCO", "TATASTEEL", "ASIANPAINT",
             "BAJFINANCE", "M&M", "HCLTECH", "ICICIBANK", "KOTAKBANK", "SUNPHARMA", "COALINDIA", "DRREDDY"]
BOOK = [("INFY", 25, 1520.00, 1468.00, 1575.40), ("SBIN", 55, 812.00, 776.00, 796.20), ("LT", 11, 3720.00, 3590.00, 3801.00), ("MARUTI", 3, 12480.00, 12050.00, 12210.00)]
ENTRY = date(2026, 12, 2)


def _pos(symbol, shares, entry, stop, last, entry_date=ENTRY, hold=False, pending=0, pending_reason="") -> Position:
    return Position(position_id=f"{SID}:{symbol}:{entry_date.isoformat()}", strategy_id=SID, symbol=symbol, sector=None, entry_date=entry_date, entry_price=entry, initial_stop=stop,
                    live_stop=stop, target=None, shares_initial=float(shares), shares_remaining=shares, risk_inr=shares * (entry - stop), exit_policy_id="mc_trailing",
                    last_close=last, hold=hold, pending_exit=pending, pending_reason=pending_reason)


def _ticket(symbol, sector, ref, stop, signal_date) -> Ticket:
    shares = int(math.floor(2000 / (ref - stop)))
    return Ticket(ticket_id=f"{SID}:{symbol}:{signal_date.isoformat()}", strategy_id=SID, symbol=symbol, sector=sector, signal_date=signal_date, reference_price=ref, stop=stop,
                  target=None, shares_planned=shares, risk_planned=shares * (ref - stop), value_planned=shares * ref, created_on=signal_date)


def _closed(sym, entry_d, exit_d, pnl, reason, excluded=False) -> ClosedTrade:
    return ClosedTrade(position_id=f"{SID}:{sym}:{entry_d.isoformat()}", strategy_id=SID, symbol=sym, entry_date=entry_d, exit_date=exit_d, entry_price=100.0, initial_stop=95.0,
                       shares_initial=400.0, risk_inr=2000.0, gross_pnl=float(pnl) + 40.0, costs=40.0, net_pnl=float(pnl), exit_reason=reason, excluded_ca=excluded)


# ------------------------------------------------------------------------------------------------------------------------------ scenario -> decisions
def _decisions_for(scenario: str):
    """(sessions, decisions list, lake closes by symbol/date, tickets file dict or None, now, last data date)."""
    if scenario == "empty":
        end = date(2026, 11, 23)
    elif scenario == "signal_day":
        end = date(2026, 12, 1)
    elif scenario in ("positions", "stale"):
        end = date(2026, 12, 22) if scenario == "positions" else date(2026, 12, 18)
    elif scenario == "trades":
        end = date(2027, 5, 14)
    else:
        end = date(2027, 9, 17)
    days = weekdays(START_DATE, end)
    decs: List[Decisions] = []
    cash = 200000.0
    closes: Dict[str, Dict[date, float]] = {}
    tickets_file: Optional[dict] = None
    realised = 0.0

    if scenario in ("empty",):
        decs = [Decisions(as_of=d, cash_after=cash) for d in days]
    elif scenario == "signal_day":
        tick = (_ticket("TCS", "IT", 3985.00, 3812.00, end), _ticket("HDFCBANK", "Financials", 1642.30, 1589.00, end), _ticket("ITC", "FMCG", 468.40, 448.60, end))
        blocked = tuple(Blocked(SID, s, "BLOCKED_BY_RISK(sector_Financials:16.1%>15.0%)", "risk")
                        for s in ("ICICIBANK", "AXISBANK", "KOTAKBANK", "SBIN", "BAJFINANCE", "INFY", "HCLTECH", "WIPRO", "TECHM", "HINDUNILVR", "NESTLEIND", "BRITANNIA"))
        decs = [Decisions(as_of=d, cash_after=cash, new_tickets=tick if d == end else (), blocked=blocked if d == end else ()) for d in days]
        tickets_file = {"as_of": end.isoformat(), "tickets": to_plain(tick), "blocked": to_plain(blocked), "flags": [], "fills_assumed": [], "exits_assumed": [], "note": "x"}
    elif scenario in ("positions", "stale"):
        sig = date(2026, 12, 1)
        cost = sum(sh * e for _, sh, e, _, _ in BOOK)
        for d in days:
            kw: dict = dict(as_of=d, cash_after=cash)
            if d == sig:
                kw["new_tickets"] = (_ticket("TCS", "IT", 3985.00, 3812.00, d),)
            if d == ENTRY:
                cash -= cost
                ups = tuple(PositionUpdate(p.position_id, p) for p in (_pos(s, sh, e, st, e, hold=(s == "SBIN")) for s, sh, e, st, _ in BOOK))
                fills = tuple(Fill(f"{SID}:{p.symbol}", p.position_id, SID, p.symbol, d, p.entry_price, p.shares_remaining, 0.0) for p in (u.position for u in ups))
                kw.update(cash_after=cash, position_updates=ups, fills=fills)
            if d == days[-1] and scenario == "positions":
                m = _pos("MARUTI", 3, 12480.0, 12050.0, 12210.0, pending=3, pending_reason="TIME_EXIT")
                kw["position_updates"] = (PositionUpdate(m.position_id, m),)
            decs.append(Decisions(**kw))
        n = len([d for d in days if d >= ENTRY])
        for s, sh, e, st, last in BOOK:
            for i, d in enumerate([d for d in days if d >= ENTRY]):
                f = i / (n - 1) if n > 1 else 1
                closes.setdefault(s, {})[d] = round(e + (last - e) * f + (0.4 * math.sin(i) if 0 < i < n - 1 else 0), 2)
        if scenario == "positions":
            for s, sh, e, st, last in BOOK:
                closes[s][days[-1]] = last
    else:
        rows = [(s, len(days) - 1 - b, h, p) for s, b, h, p in TRADES_ROWS] if scenario == "trades" else \
               [(DEEP_SYMS[i], 8 * (i + 1) + 10, 4 + (i * 7) % 22, DEEP_P[i]) for i in range(25)]
        by_exit: Dict[int, tuple] = {xi: (s, h, p) for s, xi, h, p in rows}
        for i, d in enumerate(days):
            kw = dict(as_of=d)
            if i in by_exit:
                s, h, p = by_exit[i]
                reason = "TIME_EXIT" if p > 0 else "STOP_HIT"
                kw["closed"] = (_closed(s, days[i - h], d, p, reason, excluded=(scenario == "trades" and s == "ASIANPAINT")),)
                if scenario == "trades" and s == "HCLTECH":
                    kw["flags"] = (Flag("STOP_HIT", "", SID, s), Flag("GAP_THROUGH_STOP", "", SID, s))
                elif p < 0:
                    kw["flags"] = (Flag("STOP_HIT", "", SID, s),)
                cash += p
                realised += p
            kw["cash_after"] = cash
            kw["realised_pnl_after"] = realised
            decs.append(Decisions(**kw))
    now = datetime(2026, 12, 22, 21, 0, tzinfo=IST) if scenario == "stale" else datetime.combine(days[-1], datetime.min.time(), tzinfo=IST).replace(hour=21)
    return days, decs, closes, tickets_file, now, end


# ------------------------------------------------------------------------------------------------------------------------------ files
def write_state(path: Path, decs: List[Decisions], initial_cash: float = 200000.0, with_init: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(_DDL)
    con.execute("insert into meta values ('schema_version','1')")
    st = State.initial(initial_cash)
    if with_init:
        con.execute("insert into journal (kind, session, key, payload) values ('init','0000-00-00','init',?)", (json.dumps({"cash": initial_cash}),))
    for d in decs:
        st = apply_decisions(st, d)
        con.execute("insert into journal (kind, session, key, payload) values ('decisions',?,?,?)", (d.as_of.isoformat(), d.as_of.isoformat(), d.to_json()))
        con.execute("insert or replace into snapshot (id, as_of, state) values (1, ?, ?)", (d.as_of.isoformat(), st.to_json()))
    con.commit()
    con.close()


def append_session(path: Path, d: Decisions) -> None:
    con = sqlite3.connect(path)
    con.execute("insert into journal (kind, session, key, payload) values ('decisions',?,?,?)", (d.as_of.isoformat(), d.as_of.isoformat(), d.to_json()))
    con.commit()
    con.close()


def write_lake(path: Path, days: List[date], closes: Dict[str, Dict[date, float]], sealed: Optional[date]) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE market_data_lake (id INTEGER PRIMARY KEY, symbol TEXT, trade_date TEXT, open_raw REAL, high_raw REAL, low_raw REAL, close_raw REAL, volume_raw INTEGER)")
    con.execute("CREATE TABLE _guard_seal (tbl TEXT PRIMARY KEY, sealed_through TEXT, sealed_at TEXT)")
    rows = [("NIFTY50_INDEX", d.isoformat(), 25000 + 7.5 * i + 40 * math.sin(i / 3.0)) for i, d in enumerate(days)]
    for sym, series in closes.items():
        rows += [(sym, d.isoformat(), c) for d, c in series.items()]
    con.executemany("insert into market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw) values (?,?,0,0,0,?,0)", rows)
    if sealed is not None:
        con.execute("insert into _guard_seal values ('market_data_lake', ?, 'x')", (sealed.isoformat(),))
    con.commit()
    con.close()


def build_world(tmp: Path, scenario: str, *, token: str = "test-token-123", allowed_hosts=("testserver", "localhost", "127.0.0.1")) -> World:
    days, decs, closes, tickets_file, now, end = _decisions_for(scenario)
    root = tmp / scenario
    state_db = root / "state" / "live_state.db"
    tickets = root / "state" / "tickets"
    lake = root / "finsight.db"
    data_root = root / "data"
    (data_root / "daily").mkdir(parents=True, exist_ok=True)
    (data_root / "daily" / "calendar.csv").write_text("date,checked_at,outcome,detail\n", encoding="utf-8")
    shared = root / "shared.yaml"
    shared.write_text("portfolio_risk:\n  max_loss_pct_per_trade: 1.0\n", encoding="utf-8")
    write_state(state_db, decs)
    tickets.mkdir(parents=True, exist_ok=True)
    if tickets_file is not None:
        (tickets / f"tickets_{end.isoformat()}.json").write_text(json.dumps(tickets_file), encoding="utf-8")
    write_lake(lake, days, closes, sealed=end)
    settings = Settings(host="127.0.0.1", port=8765, allowed_hosts=tuple(allowed_hosts), token=token, data_root=data_root, state_db=state_db, lake=lake, tickets_dir=tickets,
                        shared_yaml=shared, busy_timeout_s=0.2)
    return World(scenario, settings, now, root, end, decs[-1])


def sector_stub(symbol: str) -> str:
    return {"TCS": "IT", "HDFCBANK": "Financials", "ITC": "FMCG", "ICICIBANK": "Financials", "AXISBANK": "Financials", "KOTAKBANK": "Financials", "SBIN": "Financials",
            "BAJFINANCE": "Financials", "INFY": "IT", "HCLTECH": "IT", "WIPRO": "IT", "TECHM": "IT", "HINDUNILVR": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG"}.get(symbol, f"UNMAPPED:{symbol}")


def signal_stub(tail) -> bool:
    """The first trading session of a month (the same rule as the repository's ``is_signal_session``), without importing the strategy in every test."""
    return len(tail) == 2 and (tail[-1].year, tail[-1].month) != (tail[-2].year, tail[-2].month)
