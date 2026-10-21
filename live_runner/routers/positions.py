"""Position close and management router."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from data.db.connection import get_session

router = APIRouter()


class ClosePositionRequest(BaseModel):
    position_id: int
    exit_price: float = Field(gt=0, description="Exit price in ₹")
    exit_date: date = Field(description="Date the position was closed")
    exit_reason: Literal["MANUAL", "STOP_HIT", "TIME_DECAY", "EARNINGS_EXIT", "OTHER"] = "MANUAL"

    @field_validator("exit_price")
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("exit_price must be positive")
        return v


class OpenPositionRequest(BaseModel):
    watchlist_id: int
    fill_price: float = Field(gt=0, description="Fill price in ₹")
    shares: int = Field(gt=0, description="Number of shares bought")
    fill_date: date = Field(description="Date the position was filled")


@router.post("/open")
def open_position_endpoint(req: OpenPositionRequest):
    """LIVE only. Records a trade you ALREADY executed in your broker terminal. Sends nothing to any broker."""
    from config import load_config
    from engine_core.costs import CostModel
    from engine_core.mode import current_mode
    from engine_core.position_service import open_position
    from data.db.models import DailyWatchlist

    cfg = load_config()
    if current_mode(cfg) != "LIVE":
        raise HTTPException(400, "Manual open is LIVE-only. PAPER positions open automatically.")

    with get_session() as session:
        t = session.get(DailyWatchlist, req.watchlist_id)
        if t is None or t.blocked or t.execution_status != "PENDING":
            raise HTTPException(409, "Ticket not found, blocked, or already actioned")

        equity = t.risk_amount / (t.risk_pct_of_equity / 100.0) if t.risk_pct_of_equity > 0 else 0.0
        risk_ps = req.fill_price - t.live_stop_loss
        rr = (t.initial_resistance_target - req.fill_price) / risk_ps if risk_ps > 0 else 0.0
        pos = open_position(
            session,
            mode="LIVE",
            ticket=t,
            fill_date=req.fill_date,
            fill_price=req.fill_price,
            shares=req.shares,
            equity=equity,
            rr_at_fill=rr,
            fill_source="BROKER_ENTERED",
            costs=CostModel.from_config(cfg),
        )
        return {"success": True, "position_id": pos.id}


@router.post("/close")
def close_position(req: ClosePositionRequest):
    """
    Close an open position and record it in the analytics log.

    This endpoint is called after the user has manually executed the exit
    in their Kite terminal. The engine records the trade for analytics.
    """
    from config import load_config
    from engine_core.mode import current_mode

    cfg = load_config()
    if current_mode(cfg) == "PAPER":
        raise HTTPException(400, "PAPER positions close automatically")

    with get_session() as session:
        from engine_core.analytics_loop import AnalyticsLoop
        from data.db.models import ActivePosition

        loop = AnalyticsLoop(session=session, config=cfg)

        try:
            record = loop.record_closed_trade(
                position_id=req.position_id,
                exit_price=req.exit_price,
                exit_date=req.exit_date,
                exit_reason=req.exit_reason,
            )
            pos = session.get(ActivePosition, req.position_id)
            if pos:
                session.delete(pos)
                session.flush()
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return {
        "success": True,
        "trade_logged": record,
        "message": f"Position {req.position_id} closed and logged to analytics.",
    }


@router.get("/states")
def get_position_state_legend():
    """Returns the meaning of each position state — for UI reference."""
    return {
        "states": {
            "INITIAL_RISK": {
                "color": "blue",
                "description": "Position is active with initial stop-loss. Waiting for 1:1 R:R.",
                "action": "Monitor. Auto-exits to RISK_FREE_1_TO_1 on reaching 1:1.",
            },
            "RISK_FREE_1_TO_1": {
                "color": "green",
                "description": "Stop moved to breakeven (entry price). Capital no longer at risk.",
                "action": "Let it run. Auto-exits to TRAILING_ATR on clearing resistance target.",
            },
            "TRAILING_ATR": {
                "color": "gold",
                "description": "Trailing stop active at 2× ATR below highest high. Ratchets up only.",
                "action": "Monitor trailing stop. Exit manually when stop is hit.",
            },
            "PENDING_MANUAL_EXIT": {
                "color": "red",
                "description": "15 sessions elapsed without reaching 1:1. Time-decay signal.",
                "action": "⚠️ Review and exit manually. Time-based decay rule triggered.",
            },
        }
    }
