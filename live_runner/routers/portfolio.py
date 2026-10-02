"""Portfolio summary and heat cap router."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from config import load_config
from data.db.connection import get_session

router = APIRouter()


@router.get("")
def get_portfolio():
    """
    Returns current open positions with state machine status, heat cap summary,
    and sector exposure breakdown.
    """
    cfg = load_config()
    risk_cfg = cfg["risk"]

    with get_session() as session:
        positions = session.execute(
            text("SELECT * FROM active_positions ORDER BY entry_date ASC")
        ).fetchall()

    position_list = []
    total_risk = 0.0
    total_position_value = 0.0
    sector_exposure: dict[str, float] = {}

    for p in positions:
        risk_amount = p.shares * (p.entry_price - p.initial_stop_loss)
        position_value = p.shares * p.entry_price
        total_risk += risk_amount
        total_position_value += position_value

        if p.sector:
            sector_exposure[p.sector] = sector_exposure.get(p.sector, 0) + position_value

        position_list.append({
            "id": p.id,
            "symbol": p.symbol,
            "entry_date": str(p.entry_date),
            "entry_price": p.entry_price,
            "shares": p.shares,
            "position_value": round(position_value, 2),
            "live_stop_loss": p.live_stop_loss,
            "initial_stop_loss": p.initial_stop_loss,
            "initial_resistance_target": p.initial_resistance_target,
            "projected_rr": round(p.projected_rr, 2),
            "position_state": p.position_state,
            "days_held": p.days_held,
            "highest_high_since_breakout": p.highest_high_since_breakout,
            "risk_amount": round(risk_amount, 2),
            "sector": p.sector,
            "earnings_alert": bool(p.earnings_alert),
            "next_earnings_date": str(p.next_earnings_date) if p.next_earnings_date else None,
            "last_evaluated_date": str(p.last_evaluated_date) if p.last_evaluated_date else None,
        })

    account_equity = float(__import__("os").getenv("ACCOUNT_EQUITY", "1000000"))
    total_risk_pct = (total_risk / account_equity) * 100 if account_equity > 0 else 0.0

    # Sector exposure as % of total allocated capital
    sector_pct = {
        sector: round((val / total_position_value) * 100, 1)
        for sector, val in sector_exposure.items()
    } if total_position_value > 0 else {}

    return {
        "positions": position_list,
        "summary": {
            "open_positions": len(position_list),
            "max_positions": risk_cfg["max_concurrent_positions"],
            "total_risk_amount": round(total_risk, 2),
            "total_risk_pct": round(total_risk_pct, 2),
            "max_risk_pct": risk_cfg["max_total_portfolio_risk_pct"],
            "total_position_value": round(total_position_value, 2),
            "positions_capacity_used_pct": round((len(position_list) / risk_cfg["max_concurrent_positions"]) * 100, 1),
            "risk_capacity_used_pct": round((total_risk_pct / risk_cfg["max_total_portfolio_risk_pct"]) * 100, 1),
            "sector_exposure": sector_pct,
            "max_sector_pct": risk_cfg["max_sector_exposure_pct"],
            "earnings_alerts": [p["symbol"] for p in position_list if p["earnings_alert"]],
            "pending_manual_exits": [p["symbol"] for p in position_list if p["position_state"] == "PENDING_MANUAL_EXIT"],
        }
    }
