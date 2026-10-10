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


@router.post("/close")
def close_position(req: ClosePositionRequest):
    """
    Close an open position and record it in the analytics log.

    This endpoint is called after the user has manually executed the exit
    in their Kite terminal. The engine records the trade for analytics.
    """
    with get_session() as session:
        from engine_core.analytics_loop import AnalyticsLoop
        loop = AnalyticsLoop(session=session)

        try:
            record = loop.record_closed_trade(
                position_id=req.position_id,
                exit_price=req.exit_price,
                exit_date=req.exit_date,
                exit_reason=req.exit_reason,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return {
        "success": True,
        "trade_logged": record,
        "message": f"Position {req.position_id} closed and logged to analytics.",
    }


class RecordPartialExitRequest(BaseModel):
    position_id: int
    exit_price: float = Field(gt=0, description="Exit price in ₹")
    shares_sold: int = Field(gt=0, description="Number of shares sold")
    exit_date: date = Field(description="Date the partial was executed")


@router.post("/partial_close")
def record_partial_close(req: RecordPartialExitRequest):
    """
    Record a partial profit booking. Decrements shares_remaining and logs the partial exit.
    """
    with get_session() as session:
        from data.db.models import ActivePosition
        pos = session.query(ActivePosition).filter(ActivePosition.id == req.position_id).first()
        if not pos:
            raise HTTPException(status_code=404, detail="Position not found.")
            
        shares_rem = pos.shares_remaining if pos.shares_remaining is not None else pos.shares
        if req.shares_sold >= shares_rem:
            raise HTTPException(status_code=400, detail="Cannot sell all remaining shares via partial. Use full close.")
            
        pos.shares_remaining = shares_rem - req.shares_sold
        pos.partial_exit_count += 1
        
        pnl = (req.exit_price - pos.entry_price) * req.shares_sold
        pos.total_realized_pnl_partial += pnl
        
        # Log to trade_analytics_log
        from data.db.models import TradeAnalyticsLog
        one_r = pos.entry_price - pos.initial_stop_loss
        realized_rr = (req.exit_price - pos.entry_price) / one_r if one_r > 0 else 0
        
        log_entry = TradeAnalyticsLog(
            position_id=pos.id,
            symbol=pos.symbol,
            entry_date=pos.entry_date,
            exit_date=req.exit_date,
            entry_price=pos.entry_price,
            exit_price=req.exit_price,
            shares=req.shares_sold,
            initial_stop_loss=pos.initial_stop_loss,
            projected_rr=pos.projected_rr,
            realized_rr=realized_rr,
            pnl_gross=pnl,
            exit_reason="PARTIAL_PROFIT",
            regime_at_entry=None,
            regime_at_exit=None,
            sector=pos.sector,
            days_held=pos.days_held
        )
        session.add(log_entry)
        session.commit()
        
    return {"success": True, "message": f"Partial exit recorded for {req.shares_sold} shares of {pos.symbol}."}


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
