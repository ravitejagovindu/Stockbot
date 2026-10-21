"""tests/unit/test_phase2_paper.py — Comprehensive tests for Phase 2 Paper Trading framework."""
from __future__ import annotations

from datetime import date, timedelta
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from data.db.connection import Base
from data.db.models import (
    ActivePosition,
    DailyWatchlist,
    MarketDataLake,
    CorporateActionsLog,
    TradeAnalyticsLog,
)
from engine_core.costs import CostModel
from engine_core.equity import paper_cash, paper_equity, get_equity
from engine_core.account_ledger import get_live_equity
from engine_core.position_service import open_position
from engine_core.trade_metrics import trades_from_log, sharpe_from_equity, metrics_from_trades
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

def test_paper_trader_open_pending_tickets(session):
    from live_runner.paper_trader import open_pending_tickets, expire_stale_tickets

    cfg = sample_cfg(mode="PAPER")

    # Add historical dates to market_data_lake
    d1 = date(2024, 1, 2)
    d2 = date(2024, 1, 3)
    session.add(MarketDataLake(symbol="RELIANCE", trade_date=d1, open_raw=2000.0, high_raw=2050.0, low_raw=1990.0, close_raw=2020.0, volume_raw=10000, exchange="NSE"))
    session.add(MarketDataLake(symbol="RELIANCE", trade_date=d2, open_raw=2025.0, high_raw=2060.0, low_raw=2010.0, close_raw=2040.0, volume_raw=12000, exchange="NSE"))

    # Ticket generated on d1
    ticket = DailyWatchlist(
        run_date=d1,
        symbol="RELIANCE",
        entry_price=2020.0,
        live_stop_loss=1980.0,
        stop_a=1980.0,
        stop_b=1970.0,
        initial_resistance_target=2120.0,
        projected_rr=2.5,
        shares=20,
        position_value=40400.0,
        risk_amount=800.0,
        risk_pct_of_equity=0.08,
        sector="ENERGY",
        blocked=False,
        execution_status="PENDING",
    )
    session.add(ticket)
    session.flush()

    # Run on d2
    fills = open_pending_tickets(session, cfg, d2)
    assert len(fills) == 1
    assert fills[0]["status"] == "OPENED"
    assert fills[0]["symbol"] == "RELIANCE"

    # Ticket status is now OPENED
    assert ticket.execution_status == "OPENED"

    # Re-running on d2 must NOT open twice
    fills2 = open_pending_tickets(session, cfg, d2)
    assert len(fills2) == 0


def test_paper_trader_gap_up_and_corp_actions(session):
    from live_runner.paper_trader import open_pending_tickets

    cfg = sample_cfg(mode="PAPER")
    d1 = date(2024, 1, 2)
    d2 = date(2024, 1, 3)

    # Symbol 1: Gaps up +5% (limit is 3%)
    session.add(MarketDataLake(symbol="GAPCO", trade_date=d1, open_raw=100.0, high_raw=102.0, low_raw=99.0, close_raw=100.0, volume_raw=5000, exchange="NSE"))
    session.add(MarketDataLake(symbol="GAPCO", trade_date=d2, open_raw=105.0, high_raw=106.0, low_raw=104.0, close_raw=105.0, volume_raw=5000, exchange="NSE"))
    t1 = DailyWatchlist(
        run_date=d1, symbol="GAPCO", entry_price=100.0, live_stop_loss=95.0,
        stop_a=95.0, stop_b=95.0, initial_resistance_target=115.0, projected_rr=3.0,
        shares=10, position_value=1000.0, risk_amount=50.0, risk_pct_of_equity=0.005,
        blocked=False, execution_status="PENDING"
    )

    # Symbol 2: Has corporate action on d2
    session.add(MarketDataLake(symbol="CORPCO", trade_date=d1, open_raw=100.0, high_raw=102.0, low_raw=99.0, close_raw=100.0, volume_raw=5000, exchange="NSE"))
    session.add(MarketDataLake(symbol="CORPCO", trade_date=d2, open_raw=100.0, high_raw=102.0, low_raw=99.0, close_raw=100.0, volume_raw=5000, exchange="NSE"))
    session.add(CorporateActionsLog(symbol="CORPCO", ex_date=d2, action_type="SPLIT", ratio_numerator=1.0, ratio_denominator=2.0))
    t2 = DailyWatchlist(
        run_date=d1, symbol="CORPCO", entry_price=100.0, live_stop_loss=95.0,
        stop_a=95.0, stop_b=95.0, initial_resistance_target=115.0, projected_rr=3.0,
        shares=10, position_value=1000.0, risk_amount=50.0, risk_pct_of_equity=0.005,
        blocked=False, execution_status="PENDING"
    )

    session.add_all([t1, t2])
    session.flush()

    res = open_pending_tickets(session, cfg, d2)
    assert len(res) == 2
    assert t1.execution_status == "SKIPPED"
    assert "GAP_UP_TOO_LARGE" in t1.execution_note
    assert t2.execution_status == "SKIPPED"
    assert "CORP_ACTION_ON_EXEC_DATE" in t2.execution_note


def test_paper_trader_raises_in_live_mode(session):
    from live_runner.paper_trader import open_pending_tickets

    cfg = sample_cfg(mode="LIVE")
    with pytest.raises(AssertionError, match="must not run in LIVE mode"):
        open_pending_tickets(session, cfg, date(2024, 1, 3))


# ===========================================================================
# 5. Trade Metrics Tests
# ===========================================================================

def test_trade_metrics():
    df = pd.DataFrame([
        {"position_id": 1, "symbol": "A", "entry_price": 100.0, "stop": 90.0, "shares": 10, "pnl_net": 200.0, "tax_est": 40.0, "exit_date": date(2024, 1, 5)},
        {"position_id": 2, "symbol": "B", "entry_price": 50.0, "stop": 45.0, "shares": 20, "pnl_net": -100.0, "tax_est": 0.0, "exit_date": date(2024, 1, 10)},
    ])

    m = metrics_from_trades(df, start_equity=100_000.0)
    assert m["n_trades"] == 2
    assert m["win_rate_pct"] == 50.0
    assert m["net_pnl_after_tax"] == 160.0 - 100.0  # 60.0
    assert m["profit_factor"] == 160.0 / 100.0
    assert m["expectancy_r"] == (2.0 - 1.0) / 2.0  # +0.5R

    # Sharpe ratio
    eq = pd.Series([100_000, 101_000, 102_500, 102_000, 103_500])
    s = sharpe_from_equity(eq)
    assert isinstance(s, float) and s > 0


# ===========================================================================
# 6. Append-Only Trigger Tests (Step 2.10)
# ===========================================================================

def test_append_only_trigger():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TRIGGER trg_tal_no_update BEFORE UPDATE ON trade_analytics_log
            BEGIN SELECT RAISE(ABORT, 'trade_analytics_log is append-only'); END;
        """))
        conn.execute(text("""
            CREATE TRIGGER trg_tal_no_delete BEFORE DELETE ON trade_analytics_log
            BEGIN SELECT RAISE(ABORT, 'trade_analytics_log is append-only'); END;
        """))
        conn.execute(text("""
            INSERT INTO trade_analytics_log (position_id, symbol, entry_date, exit_date, entry_price, exit_price, shares, initial_stop_loss, projected_rr, realized_rr, pnl_gross, exit_reason)
            VALUES (9999, 'TEST', '2024-01-01', '2024-01-02', 100, 105, 10, 95, 2, 1, 50, 'MANUAL')
        """))
        conn.commit()

        with pytest.raises(Exception, match="trade_analytics_log is append-only"):
            conn.execute(text("DELETE FROM trade_analytics_log WHERE position_id = 9999"))

        with pytest.raises(Exception, match="trade_analytics_log is append-only"):
            conn.execute(text("UPDATE trade_analytics_log SET pnl_gross = 100 WHERE position_id = 9999"))

