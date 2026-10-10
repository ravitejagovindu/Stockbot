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

    from engine_core.account_ledger import get_live_equity
    import os
    
    with get_session() as session:
        account_equity = get_live_equity(session, float(os.getenv("ACCOUNT_EQUITY", "1000000")))
        
        symbols = [p.symbol for p in positions]
        latest_closes = {}
        if symbols:
            sym_list = ','.join([f"'{s}'" for s in symbols])
            query = f"""
            SELECT m1.symbol, m1.close_raw 
            FROM market_data_lake m1
            INNER JOIN (
                SELECT symbol, MAX(trade_date) as max_date 
                FROM market_data_lake 
                WHERE symbol IN ({sym_list})
                GROUP BY symbol
            ) m2 ON m1.symbol = m2.symbol AND m1.trade_date = m2.max_date
            """
            for row in session.execute(text(query)).fetchall():
                latest_closes[row.symbol] = row.close_raw

    sector_performance_dict = {}

    for p in positions:
        risk_amount = p.shares * (p.entry_price - p.initial_stop_loss)
        position_value = p.shares * p.entry_price
        total_risk += risk_amount
        total_position_value += position_value

        sector = p.sector or "Unknown"
        if sector not in sector_performance_dict:
            sector_performance_dict[sector] = {"total_capital_deployed": 0.0, "estimated_pnl": 0.0}
        
        sector_performance_dict[sector]["total_capital_deployed"] += position_value
        live_price = latest_closes.get(p.symbol, p.entry_price)
        sector_performance_dict[sector]["estimated_pnl"] += (live_price - p.entry_price) * p.shares

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

    total_risk_pct = (total_risk / account_equity) * 100 if account_equity > 0 else 0.0

    # Sector exposure as % of total allocated capital
    sector_pct = {
        sec: round((val / total_position_value) * 100, 1)
        for sec, val in sector_exposure.items()
    } if total_position_value > 0 else {}

    sector_performance = []
    for sec, data in sector_performance_dict.items():
        cap = data["total_capital_deployed"]
        est_pnl = data["estimated_pnl"]
        sector_performance.append({
            "sector": sec,
            "total_capital_deployed": round(cap, 2),
            "pct_of_equity": round((cap / account_equity) * 100, 2) if account_equity > 0 else 0.0,
            "estimated_pnl": round(est_pnl, 2),
            "pnl_pct": round((est_pnl / cap) * 100, 2) if cap > 0 else 0.0
        })

    return {
        "positions": position_list,
        "sector_performance": sector_performance,
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
