"""Trade analytics and strategy decay reporting router."""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import text

from data.db.connection import get_session

router = APIRouter()


@router.get("")
def get_analytics(limit: int = Query(default=200, le=1000, description="Max trades to return")):
    """
    Returns the full trade analytics log with strategy decay indicators.

    Key metric: decay_ratio = avg_realized_rr / avg_projected_rr
    - 1.0 = perfect (realizing exactly what was projected)
    - < 0.7 = concerning decay — strategy may be deteriorating
    - < 0.5 = critical — pause live trading, investigate
    """
    with get_session() as session:
        from engine_core.analytics_loop import AnalyticsLoop
        loop = AnalyticsLoop(session=session)
        report = loop.get_decay_report()

        trades = session.execute(
            text("""
                SELECT symbol, entry_date, exit_date, entry_price, exit_price,
                       shares, projected_rr, realized_rr, pnl_gross,
                       exit_reason, days_held, sector, closed_at
                FROM trade_analytics_log
                ORDER BY closed_at DESC
                LIMIT :lim
            """),
            {"lim": limit}
        ).fetchall()

    trade_list = [
        {
            "symbol": t.symbol,
            "entry_date": str(t.entry_date),
            "exit_date": str(t.exit_date),
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "shares": t.shares,
            "projected_rr": round(t.projected_rr, 2),
            "realized_rr": round(t.realized_rr, 2),
            "pnl_gross": round(t.pnl_gross, 2),
            "win": t.realized_rr > 0,
            "exit_reason": t.exit_reason,
            "days_held": t.days_held,
            "sector": t.sector,
            "closed_at": str(t.closed_at),
        }
        for t in trades
    ]

    # Decay health signal
    decay = report.get("decay_ratio")
    if decay is None:
        decay_signal = "INSUFFICIENT_DATA"
    elif decay >= 0.8:
        decay_signal = "HEALTHY"
    elif decay >= 0.6:
        decay_signal = "MONITOR"
    elif decay >= 0.5:
        decay_signal = "WARNING"
    else:
        decay_signal = "CRITICAL"

    return {
        "summary": {
            **report,
            "decay_signal": decay_signal,
            "decay_signal_description": {
                "HEALTHY": "Strategy performing as expected.",
                "MONITOR": "Mild decay detected. Watch closely.",
                "WARNING": "Significant decay. Consider pausing new entries.",
                "CRITICAL": "Critical decay. Pause live capital, investigate.",
                "INSUFFICIENT_DATA": "Not enough trades to assess.",
            }.get(decay_signal, ""),
        },
        "trades": trade_list,
    }
