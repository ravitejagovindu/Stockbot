"""Backtest adapter (restructure Phase 6 Part B): drives ``engine.decide`` over a window on the read-only lake. It holds NO decision logic.

One ``decide`` call per session (exactly the call the live adapter makes), strict mode (an error in a strategy, overlay or exit policy stops the run), mode
"backtest" (fills are assumed), network guard on, the lake opened read-only through ``stockbot.data.lake``. Positions still open after the last session are
closed at the last close x (1 - exit slippage), costs applied, reason END_OF_WINDOW, as the legacy simulator did, so trade statistics are complete.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from stockbot.backtest.no_network import network_forbidden
from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.engine.decide import EventData, decide
from stockbot.engine.types import ClosedTrade, Decisions, ExitRecord, State
from stockbot.risk.costs import CostModel


@dataclass(frozen=True)
class BacktestResult:
    decisions: tuple          # Decisions, one per session
    state: State              # after the window, END_OF_WINDOW closures included
    trades: tuple             # ClosedTrade, closing order
    equity_curve: Mapping     # date -> equity marked at the close (before the END_OF_WINDOW closure)
    end_of_window_exits: tuple


def run_backtest(lake, start: date, end: date, initial_equity: float, strategies: Sequence, policies: Mapping[str, Any], shared_config, event_data: EventData, *,
                 overlays: Optional[Mapping[str, Any]] = None, state: Optional[State] = None) -> BacktestResult:
    """``lake`` is a path (opened read-only here) or an already-open read-only connection from ``open_lake``."""
    conn = open_lake(lake) if not hasattr(lake, "execute") else lake
    end_view = AsOfView(conn, end)
    days = [d for d in end_view.sessions() if start <= d <= end]
    st = state if state is not None else State.initial(initial_equity)
    decisions: list = []
    curve: dict = {}
    with network_forbidden():
        for d in days:
            dec, st = decide(d, st, AsOfView(conn, d), strategies, shared_config, event_data, policies=policies, overlays=overlays, strict=True, mode="backtest")
            decisions.append(dec)
            curve[d] = st.cash + sum(p.shares_remaining * p.last_close for p in st.positions)
    trades = [c for dec in decisions for c in dec.closed]
    eow: list = []
    if days and st.positions:
        costs = CostModel.from_shared(shared_config.costs)
        slip = 1.0 - shared_config.execution.exit_slippage_pct / 100.0
        cash, realised = st.cash, st.realised_pnl_net
        for p in st.positions:
            price = p.last_close * slip
            sell = costs.sell_cost(price * p.shares_remaining)
            cash += price * p.shares_remaining - sell
            gross, paid = p.gross_pnl + (price - p.entry_price) * p.shares_remaining, p.costs_paid + sell
            net = gross - paid
            realised += net
            eow.append(ExitRecord(p.position_id, p.strategy_id, p.symbol, days[-1], "END_OF_WINDOW", price, p.shares_remaining, sell, True, True))
            trades.append(ClosedTrade(p.position_id, p.strategy_id, p.symbol, p.entry_date, days[-1], p.entry_price, p.initial_stop, p.shares_initial, p.risk_inr,
                                      gross, paid, net, "END_OF_WINDOW", p.hold))
        st = replace(st, positions=(), cash=cash, realised_pnl_net=realised)
    return BacktestResult(tuple(decisions), st, tuple(trades), curve, tuple(eow))
