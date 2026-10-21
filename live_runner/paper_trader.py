"""live_runner/paper_trader.py — Auto-execution of approved watchlist tickets at next open."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import func, select

from data.db.models import CorporateActionsLog, DailyWatchlist, MarketDataLake
from engine_core.costs import CostModel
from engine_core.equity import paper_cash, paper_equity
from engine_core.lifecycle_rules import plan_entry_fill
from engine_core.mode import current_mode
from engine_core.position_service import open_position


def previous_trading_date(session, eval_date: date) -> Optional[date]:
    """Get the most recent trade date strictly before eval_date in market_data_lake."""
    return session.execute(
        select(func.max(MarketDataLake.trade_date)).where(MarketDataLake.trade_date < eval_date)
    ).scalar()


def expire_stale_tickets(session, eval_date: date) -> int:
    """Mark any tickets pending from before the previous session as EXPIRED."""
    prev = previous_trading_date(session, eval_date)
    q = select(DailyWatchlist).where(
        DailyWatchlist.execution_status == "PENDING",
        DailyWatchlist.run_date < (prev or eval_date),
    )
    rows = session.execute(q).scalars().all()
    for t in rows:
        t.execution_status = "EXPIRED"
        t.execution_note = "NOT_EXECUTED_NEXT_SESSION"
    return len(rows)


def open_pending_tickets(session, config: dict, eval_date: date) -> list[dict]:
    """PAPER only. Fill yesterday's approved tickets at today's open (plus slippage)."""
    assert current_mode(config) == "PAPER", "paper_trader must not run in LIVE mode"
    prev = previous_trading_date(session, eval_date)
    if prev is None:
        return []

    ex = config.get("execution", {})
    costs = CostModel.from_config(config)

    tickets = (
        session.execute(
            select(DailyWatchlist)
            .where(
                DailyWatchlist.run_date == prev,
                DailyWatchlist.blocked.is_(False),
                DailyWatchlist.execution_status == "PENDING",
            )
            .order_by(DailyWatchlist.id)
        )
        .scalars()
        .all()
    )

    results = []
    equity = paper_equity(session, config)
    cash = paper_cash(session, config)

    for t in tickets:
        bar = session.execute(
            select(MarketDataLake.open_raw).where(
                MarketDataLake.symbol == t.symbol,
                MarketDataLake.trade_date == eval_date,
            )
        ).scalar()
        if bar is None:
            t.execution_status = "SKIPPED"
            t.execution_note = "NO_BAR_ON_EXEC_DATE"
            results.append({"symbol": t.symbol, "status": "SKIPPED", "reason": "NO_BAR_ON_EXEC_DATE"})
            continue

        ca = session.execute(
            select(CorporateActionsLog.id).where(
                CorporateActionsLog.symbol == t.symbol,
                CorporateActionsLog.ex_date == eval_date,
            )
        ).first()
        if ca:
            t.execution_status = "SKIPPED"
            t.execution_note = "CORP_ACTION_ON_EXEC_DATE"
            results.append({"symbol": t.symbol, "status": "SKIPPED", "reason": "CORP_ACTION_ON_EXEC_DATE"})
            continue

        plan = plan_entry_fill(
            ticket_entry=t.entry_price,
            stop=t.live_stop_loss,
            target=t.initial_resistance_target,
            next_open=float(bar),
            equity=equity,
            risk_pct=float(config["risk"]["max_loss_pct_per_trade"]),
            slippage_pct=float(ex.get("entry_slippage_pct", 0.0)),
            max_gap_up_pct=float(ex.get("max_entry_gap_up_pct", 3.0)),
            min_rr=float(ex.get("min_rr_at_fill", 1.5)),
            cash=cash,
        )

        if not plan.ok:
            t.execution_status = "SKIPPED"
            t.execution_note = plan.reason[:80]
            results.append({"symbol": t.symbol, "status": "SKIPPED", "reason": plan.reason})
            continue

        open_position(
            session,
            mode="PAPER",
            ticket=t,
            fill_date=eval_date,
            fill_price=plan.fill_price,
            shares=plan.shares,
            equity=equity,
            rr_at_fill=plan.rr_at_fill,
            fill_source="SIMULATED",
            costs=costs,
        )
        cash -= plan.fill_price * plan.shares
        results.append(
            {
                "symbol": t.symbol,
                "status": "OPENED",
                "price": plan.fill_price,
                "shares": plan.shares,
            }
        )

    return results
