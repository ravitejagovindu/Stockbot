"""engine_core/equity.py — paper vs live equity and cash tracking."""
from __future__ import annotations

from sqlalchemy import text


def paper_equity(session, config: dict) -> float:
    """Calculate paper account equity = starting capital + realized net PnL (net of tax)."""
    start = float(config.get("runtime", {}).get("paper_start_equity", 1_000_000.0))
    realized = session.execute(
        text("SELECT COALESCE(SUM(pnl_net - tax_est), 0) FROM trade_analytics_log WHERE mode='PAPER'")
    ).scalar()
    return start + float(realized or 0.0)


def paper_cash(session, config: dict) -> float:
    """Calculate available cash in paper mode = paper_equity - currently invested capital."""
    invested = session.execute(
        text(
            "SELECT COALESCE(SUM(COALESCE(shares_remaining, shares) * entry_price), 0) "
            "FROM active_positions WHERE mode='PAPER'"
        )
    ).scalar()
    return paper_equity(session, config) - float(invested or 0.0)


def get_equity(session, config: dict, mode: str, live_fallback: float) -> float:
    """Dispatch equity lookup based on runtime mode."""
    if mode == "PAPER":
        return paper_equity(session, config)
    from engine_core.account_ledger import get_live_equity
    return get_live_equity(session, live_fallback)
