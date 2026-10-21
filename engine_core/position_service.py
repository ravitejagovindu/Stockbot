"""engine_core/position_service.py — unified position opening logic.

Used by both PAPER (automated next-open fill) and LIVE (operator entered fill).
"""
from __future__ import annotations

from datetime import date

from data.db.models import ActivePosition, DailyWatchlist
from engine_core.costs import CostModel


def open_position(
    session,
    *,
    mode: str,
    ticket: DailyWatchlist,
    fill_date: date,
    fill_price: float,
    shares: int,
    equity: float,
    rr_at_fill: float,
    fill_source: str,
    costs: CostModel,
) -> ActivePosition:
    """Create an ActivePosition record and link it to the daily watchlist ticket."""
    pos = ActivePosition(
        symbol=ticket.symbol,
        entry_date=fill_date,
        entry_price=fill_price,
        shares=shares,
        original_shares=shares,
        shares_remaining=shares,
        initial_stop_loss=ticket.live_stop_loss,
        live_stop_loss=ticket.live_stop_loss,
        initial_resistance_target=ticket.initial_resistance_target,
        projected_rr=rr_at_fill,
        position_state="INITIAL_RISK",
        days_held=0,
        highest_high_since_breakout=fill_price,
        sector=ticket.sector,
        account_equity_at_entry=equity,
        stop_a_at_entry=ticket.stop_a,
        stop_b_at_entry=ticket.stop_b,
        mode=mode,
        fill_source=fill_source,
        entry_costs=costs.buy_cost(fill_price * shares),
    )
    session.add(pos)
    session.flush()
    ticket.execution_status = "OPENED"
    ticket.position_id = pos.id
    return pos
