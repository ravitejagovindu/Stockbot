"""tests/unit/test_phase2_paper.py — Comprehensive tests for Phase 2 Paper Trading framework."""
from __future__ import annotations

from datetime import date, timedelta
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from stockbot.data.db.connection import Base
from stockbot.data.db.models import (
    ActivePosition,
    DailyWatchlist,
    MarketDataLake,
    CorporateActionsLog,
    TradeAnalyticsLog,
)
from stockbot.risk.costs import CostModel
from stockbot.live.equity import paper_cash, paper_equity, get_equity
from stockbot.live.account_ledger import get_live_equity
from stockbot.live.position_service import open_position
from stockbot.validation.trade_metrics import trades_from_log, sharpe_from_equity, metrics_from_trades
import pandas as pd


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()
    engine.dispose()


def sample_cfg(mode="PAPER"):
    return {
        "runtime": {"mode": mode, "paper_start_equity": 1_000_000.0},
        "costs": {
            "stt_buy_pct": 0.1,
            "stt_sell_pct": 0.1,
            "brokerage_per_order_inr": 0.0,
            "exchange_txn_pct": 0.00297,
            "sebi_fee_pct": 0.0001,
            "stamp_duty_buy_pct": 0.015,
            "gst_pct": 18.0,
            "dp_charge_per_sell_inr": 15.34,
            "stcg_tax_pct": 20.0,
        },
        "risk": {
            "max_loss_pct_per_trade": 1.0,
            "atr_period": 14,
            "trailing_stop_atr_multiplier": 2.0,
            "trailing_stop_atr_multiplier_kill_switch": 2.0,
        },
        "execution": {
            "entry_slippage_pct": 0.1,
            "exit_slippage_pct": 0.0,
            "max_entry_gap_up_pct": 3.0,
            "min_rr_at_fill": 1.5,
        },
        "trade_management": {"time_decay_sessions": 15, "earnings_alert_days": 7},
    }


# ===========================================================================
# 1. Cost and Tax Model Tests
# ===========================================================================

def test_cost_model_buy_sell_tax():
    cfg = sample_cfg()
    cm = CostModel.from_config(cfg)

    # 1 Lakh buy
    buy_c = cm.buy_cost(100_000.0)
    assert 115.0 <= buy_c <= 125.0, f"Expected ~118.62, got {buy_c}"

    # 1 Lakh sell
    sell_c = cm.sell_cost(100_000.0)
    assert 115.0 <= sell_c <= 125.0, f"Expected ~118.96, got {sell_c}"

    # Tax on positive gain
    assert cm.tax_on_gain(10_000.0) == 2000.0
    # Tax on loss is zero
    assert cm.tax_on_gain(-5000.0) == 0.0


# ===========================================================================
# 2. Paper Equity & Cash Isolation Tests
# ===========================================================================

def test_paper_equity_and_live_isolation(session):
    cfg = sample_cfg()
    assert paper_equity(session, cfg) == 1_000_000.0

    # Insert a PAPER trade log
    session.add(
        TradeAnalyticsLog(
            position_id=1,
            symbol="INFY",
            entry_date=date(2024, 1, 1),
            exit_date=date(2024, 1, 10),
            entry_price=100.0,
            exit_price=110.0,
            shares=100,
            initial_stop_loss=95.0,
            projected_rr=2.0,
            realized_rr=2.0,
            pnl_gross=1000.0,
            exit_reason="STOP_HIT",
            days_held=9,
            mode="PAPER",
            costs_total=20.0,
            pnl_net=980.0,
            tax_est=196.0,
        )
    )
    session.flush()

    # Paper equity reflects after-tax realized gain (980 - 196 = 784)
    assert paper_equity(session, cfg) == 1_000_784.0

    # Live equity must be completely unaffected by paper trades
    live_eq = get_live_equity(session, 500_000.0)
    assert live_eq == 500_000.0

    # get_equity dispatch
    assert get_equity(session, cfg, "PAPER", 500_000.0) == 1_000_784.0
    assert get_equity(session, cfg, "LIVE", 500_000.0) == 500_000.0


def test_paper_cash(session):
    cfg = sample_cfg()

    # Open paper position of 50 shares @ 200 = 10,000
    pos = ActivePosition(
        symbol="TCS",
        entry_date=date(2024, 1, 2),
        entry_price=200.0,
        shares=50,
        shares_remaining=50,
        initial_stop_loss=190.0,
        live_stop_loss=190.0,
        initial_resistance_target=220.0,
        projected_rr=2.0,
        days_held=1,
        highest_high_since_breakout=200.0,
        account_equity_at_entry=1_000_000.0,
        stop_a_at_entry=190.0,
        stop_b_at_entry=190.0,
        mode="PAPER",
    )
    session.add(pos)
    session.flush()

    # Cash = equity (1,000,000) - invested (10,000) = 990,000
    assert paper_cash(session, cfg) == 990_000.0


# ===========================================================================
# 3. Position Service Tests
# ===========================================================================

def test_open_position_service(session):
    cfg = sample_cfg()
    cm = CostModel.from_config(cfg)

    ticket = DailyWatchlist(
        run_date=date(2024, 1, 2),
        symbol="HDFC",
        entry_price=100.0,
        live_stop_loss=95.0,
        stop_a=95.0,
        stop_b=94.0,
        initial_resistance_target=110.0,
        projected_rr=2.0,
        shares=50,
        position_value=5000.0,
        risk_amount=250.0,
        risk_pct_of_equity=0.25,
        sector="FINANCIAL",
        blocked=False,
        execution_status="PENDING",
    )
    session.add(ticket)
    session.flush()

    pos = open_position(
        session,
        mode="PAPER",
        ticket=ticket,
        fill_date=date(2024, 1, 3),
        fill_price=100.5,
        shares=50,
        equity=1_000_000.0,
        rr_at_fill=1.73,
        fill_source="SIMULATED",
        costs=cm,
    )

    assert pos.id is not None
    assert pos.mode == "PAPER"
    assert pos.symbol == "HDFC"
    assert pos.shares == 50
    assert pos.entry_price == 100.5
    assert pos.fill_source == "SIMULATED"
    assert ticket.execution_status == "OPENED"
    assert ticket.position_id == pos.id


# ===========================================================================
# 4. Paper Trader Execution & Edge Cases
# ===========================================================================
