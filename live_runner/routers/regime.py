"""Macro regime status router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from config import load_config
from data.db.connection import get_session

router = APIRouter()


@router.get("")
def get_regime():
    """
    Returns the current macro kill switch state.
    Used by the Dashboard and Watchlist page to show regime banner.
    """
    with get_session() as session:
        result = session.execute(
            text("SELECT * FROM regime_state ORDER BY eval_date DESC LIMIT 1")
        ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="No regime state found. Run the EOD pipeline first.")

    cfg = load_config()["macro"]

    return {
        "eval_date": str(result.eval_date),
        "kill_switch_active": bool(result.kill_switch_active),
        "nifty_close": result.nifty_close,
        "nifty_sma200": result.nifty_sma200,
        "nifty_sma50": result.nifty_sma50,
        "vix_close": result.vix_close,
        "trigger_reason": result.trigger_reason,
        "reentry_consecutive_count": result.reentry_consecutive_count,
        "reentry_sessions_required": cfg["reentry_consecutive_sessions"],
        "reentry_progress_pct": round(
            (result.reentry_consecutive_count / cfg["reentry_consecutive_sessions"]) * 100, 1
        ) if result.kill_switch_active else None,
    }
