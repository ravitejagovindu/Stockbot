from sqlalchemy import select, func
from data.db.models import AccountLedger, TradeAnalyticsLog
import logging

logger = logging.getLogger(__name__)

def get_live_equity(session, fallback_equity: float) -> float:
    """
    Calculates true live equity: Deposits + Withdrawals + Realized PnL.
    Falls back to config if no deposits exist.
    """
    # Check for any deposits
    deposit_count = session.execute(
        select(func.count(AccountLedger.id))
        .where(AccountLedger.transaction_type == 'DEPOSIT')
    ).scalar() or 0

    if deposit_count == 0:
        logger.info("No ledger entries found. Falling back to env ACCOUNT_EQUITY.")
        return fallback_equity

    # Sum ledger amounts (deposits positive, withdrawals negative)
    ledger_sum = session.execute(
        select(func.sum(AccountLedger.amount_inr))
        .where(AccountLedger.transaction_type.in_(['DEPOSIT', 'WITHDRAWAL']))
    ).scalar() or 0.0

    # Sum realized PnL from closed trades
    pnl_sum = session.execute(
        select(func.sum(TradeAnalyticsLog.pnl_gross))
    ).scalar() or 0.0

    return float(ledger_sum + pnl_sum)
