"""Pure builders: turn what the readers returned into the contract's responses. No I/O here (the one file read is ``load_marks`` / ``load_risk_pct``, on small yaml files passed in).

Choices that resolve the gaps listed in docs/android/contract/SOURCE_MAP.md are named in the docstrings and written up in docs/bff/STAGE3_REPORT.md.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import yaml

from bff import config as _config  # noqa: F401  (puts the repo root on sys.path)
from bff import models as M
from stockbot.engine.apply import apply_decisions
from stockbot.engine.types import ClosedTrade, Decisions, Position, State

IST = timezone(timedelta(hours=5, minutes=30))
NEXT_SIGNAL_RULE = "first trading day of next month"
# The 19:30 IST job should have finished by this time; from then on the day's data is expected (gap 6).
JOB_DONE_AT = time(20, 30)


class BuildError(RuntimeError):
    """The data read is not enough to build a response (for example the lake has no Nifty close for the start date). The API answers 503 NOT_READY."""


# ------------------------------------------------------------------------------------------------------------------------------ money
def to_paise(rupees: float) -> int:
    """Whole paise, half up. Every stored rupee value goes through here once; totals are then sums of these integers (gap 1)."""
    return int((Decimal(repr(float(rupees))) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pct2(value: float) -> float:
    return float(Decimal(repr(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------------------------------------------------------------------ freshness
def iso_ist(now: datetime) -> str:
    return now.astimezone(IST).replace(microsecond=0).isoformat()


def expected_as_of(now: datetime, no_file_days: Set[date]) -> date:
    """The last trading day on which data is expected (gap 6).

    Start from today when it is 20:30 IST or later (the 19:30 job should have finished), otherwise from yesterday; then step back over weekends and over the days the daily
    data job recorded as having no file. Limit: a holiday the data job has not recorded yet (it records a no-file day after its attempt, and a day stays PENDING until 23:45) looks
    like a missing day until then, so the app may show "Updated N days ago" for up to a day on a new holiday; weekends and recorded holidays are never wrong."""
    local = now.astimezone(IST)
    d = local.date() if local.time() >= JOB_DONE_AT else local.date() - timedelta(days=1)
    while d.weekday() >= 5 or d in no_file_days:
        d -= timedelta(days=1)
    return d


@dataclass(frozen=True)
class Env:
    """The three freshness fields every response carries."""
    data_as_of: date
    expected: date
    generated_at: str

    def kw(self) -> dict:
        return {"apiVersion": "1", "dataAsOf": self.data_as_of, "expectedAsOf": self.expected, "generatedAt": self.generated_at}


def make_env(data_as_of: date, now: datetime, no_file_days: Set[date]) -> Env:
    return Env(data_as_of, expected_as_of(now, no_file_days), iso_ist(now))


# ------------------------------------------------------------------------------------------------------------------------------ config files
def load_marks(path: Path) -> M.Marks:
    d = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    verdict = str(d["verdict"]).strip().replace("_", " ").lower()
    return M.Marks(drawdownReviewPct=float(d["drawdown_review_pct"]), closedTradesTarget=int(d["closed_trades_target"]), verdict=verdict)


def load_risk_pct(shared_yaml: Path) -> float:
    d = yaml.safe_load(Path(shared_yaml).read_text(encoding="utf-8"))
    return float(d["portfolio_risk"]["max_loss_pct_per_trade"])


# ------------------------------------------------------------------------------------------------------------------------------ the journal fold
@dataclass(frozen=True)
class Folded:
    states: Tuple[State, ...]                 # the state after each processed session, oldest first
    decisions: Tuple[Decisions, ...]
    start_date: date                          # the first processed session (gap 2: the init row has no real date)
    data_as_of: date                          # the last processed session


def fold(decisions: Sequence[Decisions], initial_cash: float) -> Folded:
    """Fold the journal session by session (the same fold as ``StateStore.rebuild``): positions, cash, realised P&L after each session."""
    if not decisions:
        raise BuildError("no session has been processed")
    ordered = sorted(decisions, key=lambda d: d.as_of)
    st = State.initial(initial_cash)
    states: List[State] = []
    for d in ordered:
        st = apply_decisions(st, d)
        states.append(st)
    return Folded(tuple(states), tuple(ordered), ordered[0].as_of, ordered[-1].as_of)


def symbols_held(f: Folded) -> Set[str]:
    return {p.symbol for s in f.states for p in s.positions}


def state_on(f: Folded, day: date) -> State:
    """The state after the last session on or before ``day``."""
    idx = bisect_right([s.as_of for s in f.states], day) - 1
    if idx < 0:
        raise BuildError(f"no state on or before {day}")
    return f.states[idx]


def mark_price(closes: Mapping[Tuple[str, date], float], symbols_dates: Mapping[str, List[date]], pos: Position, day: date) -> float:
    """The lake close of the symbol on ``day``; else its latest earlier close in the lake; else the engine's own ``last_close`` of the position."""
    c = closes.get((pos.symbol, day))
    if c is not None:
        return c
    ds = symbols_dates.get(pos.symbol, [])
    i = bisect_right(ds, day) - 1
    if i >= 0:
        return closes[(pos.symbol, ds[i])]
    return pos.last_close


def _index_dates(closes: Mapping[Tuple[str, date], float]) -> Dict[str, List[date]]:
    out: Dict[str, List[date]] = {}
    for (s, d) in closes:
        out.setdefault(s, []).append(d)
    for v in out.values():
        v.sort()
    return out


def value_on(f: Folded, closes: Mapping[Tuple[str, date], float], day: date, idx: Optional[Dict[str, List[date]]] = None) -> Tuple[int, int, List[Tuple[Position, int]]]:
    """(cash paise, equity paise, [(position, last-close paise)]) on ``day``: positions marked at the lake close of that day. Equity = cash + sum(shares x close), all in integer paise."""
    idx = idx if idx is not None else _index_dates(closes)
    st = state_on(f, day)
    cash = to_paise(st.cash)
    marked = [(p, to_paise(mark_price(closes, idx, p, day))) for p in st.positions if p.shares_remaining > 0]
    return cash, cash + sum(p.shares_remaining * px for p, px in marked), marked


# ------------------------------------------------------------------------------------------------------------------------------ mappings
def map_block_reason(reason: str, stage: str) -> str:
    """Engine block label to the contract enum (CONTRACT.md, "Engine mapping")."""
    r = (reason or "").strip()
    if r.startswith("BLOCKED_BY_RISK"):
        inner = r[len("BLOCKED_BY_RISK("):] if r.startswith("BLOCKED_BY_RISK(") else ""
        return "SECTOR_CAP" if inner.startswith("sector_") else "RISK_CAP"
    if r == "SIZE_ZERO" and stage == "fill":
        return "CASH"
    return "OTHER"


def map_exit_reason(reason: str, gap_flagged: bool) -> str:
    if reason == "STOP_HIT":
        return "GAP_THROUGH_STOP" if gap_flagged else "STOP_HIT"
    return "OTHER"


def _sector(symbol: str, stored: Optional[str], sector_for: Callable[[str], str]) -> Optional[str]:
    s = stored or sector_for(symbol)
    return None if (s is None or str(s).startswith("UNMAPPED:")) else str(s)


PENDING_NOTES = {"TIME_EXIT": "Time exit queued at the close", "STOP_HIT": "Stop exit queued at the close"}


# ------------------------------------------------------------------------------------------------------------------------------ /v1/today
def default_signal_fn(tail: Sequence[date]) -> bool:
    """True on the first trading session of a calendar month: the repository's own ``is_signal_session`` run on a one-method calendar view of the lake's Nifty dates."""
    from stockbot.strategies.momentum_calm.strategy import is_signal_session    # imported lazily: it loads the strategy registry (about 9 s the first time)

    class _View:
        def sessions(self, lookback=None):
            return list(tail)[-lookback:] if lookback else list(tail)

    return bool(is_signal_session(_View()))


def build_today(f: Folded, tickets_file: Optional[dict], calendar_tail: Sequence[date], env: Env, risk_pct: float,
                sector_for: Callable[[str], str], signal_fn: Callable[[Sequence[date]], bool] = default_signal_fn) -> M.Today:
    last = f.decisions[-1]
    if tickets_file is not None and tickets_file.get("as_of") == last.as_of.isoformat():
        raw_tickets = tickets_file.get("tickets", [])
        raw_blocked = tickets_file.get("blocked", [])
    else:                                                                        # no file for the day: the journal holds the same lists
        raw_tickets = [_plain_ticket(t) for t in last.new_tickets]
        raw_blocked = [{"symbol": b.symbol, "reason": b.reason, "stage": b.stage} for b in last.blocked]
    tickets: List[M.Ticket] = []
    for t in raw_tickets:
        shares = int(t["shares_planned"])
        ref, stop = to_paise(t["reference_price"]), to_paise(t["stop"])
        tickets.append(M.Ticket(symbol=t["symbol"], sector=_sector(t["symbol"], t.get("sector"), sector_for), shares=shares,
                                entryReferencePaise=ref, stopPaise=stop, riskPaise=shares * (ref - stop)))
    blocked = [M.BlockedItem(symbol=b["symbol"], sector=_sector(b["symbol"], None, sector_for), reason=map_block_reason(b.get("reason", ""), b.get("stage", "")))
               for b in raw_blocked]
    state = f.states[-1]
    pending = [M.PendingFill(symbol=p.symbol, side="SELL", shares=min(p.pending_exit, p.shares_remaining),
                             note=PENDING_NOTES.get(p.pending_reason, "Exit queued at the close"))
               for p in sorted(state.positions, key=lambda p: (p.entry_date, p.symbol)) if p.pending_exit > 0 and p.shares_remaining > 0]
    return M.Today(**env.kw(), isSignalDay=bool(tickets) or bool(signal_fn(calendar_tail)), riskPerTradePct=risk_pct, tickets=tickets, blocked=blocked,
                   pendingFills=pending, nextSignalRule=NEXT_SIGNAL_RULE)


def _plain_ticket(t) -> dict:
    return {"symbol": t.symbol, "sector": t.sector, "reference_price": t.reference_price, "stop": t.stop, "shares_planned": t.shares_planned}


# ------------------------------------------------------------------------------------------------------------------------------ /v1/trades
def build_trade_rows(f: Folded) -> List[M.ClosedTrade]:
    """Every closed trade in the journal, newest exit first. ``corporateActionFlag`` is the engine's ``excluded_ca``. GAP_THROUGH_STOP comes from the gap flag of the exit session (gap 4)."""
    gap_by_session: Dict[date, Set[str]] = {}
    for d in f.decisions:
        gap_by_session[d.as_of] = {fl.symbol for fl in d.flags if fl.code == "GAP_THROUGH_STOP" and fl.symbol}
    rows: List[Tuple[Tuple, M.ClosedTrade]] = []
    for d in f.decisions:
        for c in d.closed:
            rows.append(((c.exit_date, c.entry_date, c.symbol), _trade_row(c, c.symbol in gap_by_session.get(c.exit_date, set()))))
    rows.sort(key=lambda r: r[0], reverse=True)
    return [r for _, r in rows]


def _trade_row(c: ClosedTrade, gap: bool) -> M.ClosedTrade:
    r = (c.net_pnl / c.risk_inr) if c.risk_inr else 0.0
    return M.ClosedTrade(symbol=c.symbol, entryDate=c.entry_date, exitDate=c.exit_date, exitReason=map_exit_reason(c.exit_reason, gap), netPnlPaise=to_paise(c.net_pnl),
                         netR=pct2(r), corporateActionFlag=bool(c.excluded_ca))


def build_stats(trades: Sequence[M.ClosedTrade]) -> M.TradeStats:
    """Win rate and profit factor leave out flagged trades; ``tradeCount`` counts all of them and ``excludedFromStats`` says how many were left out."""
    used = [t for t in trades if not t.corporateActionFlag]
    wins = sum(1 for t in used if t.netPnlPaise > 0)
    losses = sum(1 for t in used if t.netPnlPaise < 0)
    gw = sum(t.netPnlPaise for t in used if t.netPnlPaise > 0)
    gl = -sum(t.netPnlPaise for t in used if t.netPnlPaise < 0)
    return M.TradeStats(tradeCount=len(trades), wins=wins, losses=losses,
                        winRatePct=pct2(wins * 100 / len(used)) if used else None,
                        profitFactor=pct2(gw / gl) if gl else None,
                        excludedFromStats=len(trades) - len(used))


def build_trades(f: Folded, env: Env) -> M.Trades:
    rows = build_trade_rows(f)
    return M.Trades(**env.kw(), trades=rows, stats=build_stats(rows))


# ------------------------------------------------------------------------------------------------------------------------------ /v1/positions
def build_positions(f: Folded, closes: Mapping[Tuple[str, date], float], env: Env) -> M.Positions:
    cash, _eq, marked = value_on(f, closes, f.data_as_of)
    rows = []
    for p, last in sorted(marked, key=lambda m: (m[0].entry_date, m[0].symbol)):
        entry = to_paise(p.entry_price)
        rows.append(M.Position(symbol=p.symbol, shares=p.shares_remaining, entryDate=p.entry_date, entryPricePaise=entry, stopPaise=to_paise(p.live_stop),
                               lastClosePaise=last, unrealisedPnlPaise=p.shares_remaining * (last - entry), corporateActionFlag=bool(p.hold)))
    return M.Positions(**env.kw(), cashPaise=cash, positions=rows)


# ------------------------------------------------------------------------------------------------------------------------------ /v1/account
def _drawdowns(values: Sequence[int]) -> Tuple[float, float]:
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = max(worst, (peak - v) / peak * 100.0)
    now = (peak - values[-1]) / peak * 100.0
    return pct2(now), pct2(max(worst, now))


def rebase(nifty_close: float, nifty_start: float, start_paise: int) -> int:
    """Nifty rebased so that its close on the start date equals the starting capital, in whole paise (gap 3)."""
    return int((Decimal(start_paise) * Decimal(repr(nifty_close)) / Decimal(repr(nifty_start))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def build_account(f: Folded, initial_cash: float, closes: Mapping[Tuple[str, date], float], nifty: Mapping[date, float], closed_count: int,
                  marks: M.Marks, env: Env) -> M.Account:
    """Daily curve over the Nifty trading days from the start date to the data date; each day the state of the last processed session is marked at that day's lake closes (gap 2)."""
    start_paise = to_paise(initial_cash)
    days = sorted(d for d in nifty if f.start_date <= d <= f.data_as_of)
    if not days or days[0] != f.start_date or days[-1] != f.data_as_of:
        raise BuildError("the lake has no Nifty close for the start date or the data date")
    idx = _index_dates(closes)
    nifty0 = nifty[f.start_date]
    curve = []
    for d in days:
        _cash, equity, _m = value_on(f, closes, d, idx)
        curve.append(M.CurvePoint(date=d, accountPaise=equity, niftyPaise=rebase(nifty[d], nifty0, start_paise)))
    cash, equity, _ = value_on(f, closes, f.data_as_of, idx)
    assert equity == curve[-1].accountPaise
    now_dd, worst_dd = _drawdowns([p.accountPaise for p in curve])
    summary = M.AccountSummary(startDate=f.start_date, startingCapitalPaise=start_paise, equityPaise=equity, cashPaise=cash,
                               returnPct=pct2((equity / start_paise - 1) * 100), niftyReturnPct=pct2((curve[-1].niftyPaise / start_paise - 1) * 100),
                               drawdownNowPct=now_dd, drawdownWorstPct=worst_dd, closedTrades=closed_count)
    return M.Account(**env.kw(), summary=summary, curve=curve, marks=marks)


# ------------------------------------------------------------------------------------------------------------------------------ errors
def error_body(code: str, message: str) -> dict:
    return {"apiVersion": "1", "error": {"code": code, "message": message}}
