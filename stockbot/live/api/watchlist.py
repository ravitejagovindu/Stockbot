"""Today's approved trade setups (watchlist) router."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import text

from data.db.connection import get_session

router = APIRouter()


@router.get("")
def get_watchlist(run_date: date = Query(default=None, description="Date to fetch watchlist for. Defaults to today.")):
    """
    Returns today's approved Trade Tickets.

    These are new setups that passed ALL gates:
    - Macro regime ACTIVE
    - Liquidity, age, ASM/GSM, earnings gates
    - R:R >= 1.5
    - Portfolio heat cap not breached

    The user must manually execute these in their Kite terminal.
    NO automated order routing — SEBI compliant.
    """
    if run_date is None:
        run_date = date.today()

    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT * FROM daily_watchlist
                WHERE run_date = :rd
                ORDER BY id ASC
            """),
            {"rd": str(run_date)}
        ).fetchall()

    approved = []
    blocked = []

    for r in rows:
        item = {
            "id": r.id,
            "symbol": r.symbol,
            "run_date": str(r.run_date),
            "entry_price": r.entry_price,
            "live_stop_loss": r.live_stop_loss,
            "stop_a": r.stop_a,
            "stop_b": r.stop_b,
            "active_stop": "STOP_A" if r.stop_a < r.stop_b else "STOP_B",  # Which stop is wider (lower)
            "initial_resistance_target": r.initial_resistance_target,
            "projected_rr": round(r.projected_rr, 2),
            "shares": r.shares,
            "position_value": round(r.position_value, 2),
            "risk_amount": round(r.risk_amount, 2),
            "risk_pct_of_equity": round(r.risk_pct_of_equity, 3),
            "sector": r.sector,
            "blocked": r.blocked,
            "block_reason": r.block_reason,
            "execution_status": getattr(r, "execution_status", "PENDING"),
            "execution_note": getattr(r, "execution_note", None),
            "position_id": getattr(r, "position_id", None),
        }
        if r.blocked:
            blocked.append(item)
        else:
            approved.append(item)

    return {
        "run_date": str(run_date),
        "approved_count": len(approved),
        "blocked_count": len(blocked),
        "approved": approved,
        "blocked": blocked,
    }
