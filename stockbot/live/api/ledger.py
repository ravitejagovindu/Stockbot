from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
import os

from data.db.connection import get_session
from data.db.models import AccountLedger, TradeAnalyticsLog
from engine_core.account_ledger import get_live_equity

router = APIRouter()

class LedgerRequest(BaseModel):
    amount: float
    notes: str | None = None

@router.get("/summary")
def get_summary():
    with get_session() as session:
        fallback = float(os.getenv("ACCOUNT_EQUITY", "1000000"))
        live_equity = get_live_equity(session, fallback)
        
        total_deposits = session.execute(
            select(func.sum(AccountLedger.amount_inr))
            .where(AccountLedger.transaction_type == 'DEPOSIT')
        ).scalar() or 0.0
        
        total_withdrawals = session.execute(
            select(func.sum(AccountLedger.amount_inr))
            .where(AccountLedger.transaction_type == 'WITHDRAWAL')
        ).scalar() or 0.0
        
        total_pnl = session.execute(
            select(func.sum(TradeAnalyticsLog.pnl_gross))
        ).scalar() or 0.0

        fallback_used = (total_deposits == 0)

    return {
        "live_equity": live_equity,
        "total_deposits": total_deposits,
        "total_withdrawals": abs(total_withdrawals),
        "total_realized_pnl": total_pnl,
        "fallback_used": fallback_used
    }

@router.post("/deposit")
def deposit(req: LedgerRequest):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    with get_session() as session:
        entry = AccountLedger(
            transaction_date=date.today(),
            transaction_type='DEPOSIT',
            amount_inr=req.amount,
            notes=req.notes
        )
        session.add(entry)
        session.commit()
    return get_summary()

@router.post("/withdraw")
def withdraw(req: LedgerRequest):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    with get_session() as session:
        # Store as negative
        entry = AccountLedger(
            transaction_date=date.today(),
            transaction_type='WITHDRAWAL',
            amount_inr=-req.amount,
            notes=req.notes
        )
        session.add(entry)
        session.commit()
    return get_summary()
