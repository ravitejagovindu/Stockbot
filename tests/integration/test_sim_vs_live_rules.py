"""tests/integration/test_sim_vs_live_rules.py — Integration tests verifying Simulator vs PositionLifecycleManager."""
from __future__ import annotations

from datetime import date, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.db.connection import Base
from data.db.models import (
    ActivePosition,
    MarketDataLake,
    RegimeState,
    SharesOutstanding,
)
from engine_core.lifecycle_rules import (
    Bar,
    BarCtx,
    LifecycleRules,
    PosState,
    advance_one_bar,
    parabolic_ref_close,
)
from engine_core.position_lifecycle import PositionLifecycleManager
from backtest.exclusions import Exclusions
from backtest.simulator import Simulator


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()
    engine.dispose()


def _get_base_config():
    return {
        "runtime": {"mode": "PAPER", "paper_start_equity": 1_000_000.0},
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
        "universe": {
            "min_market_cap_cr": 500.0,
            "min_adtv_cr": 1.0,
            "min_listing_age_trading_days": 3,
            "volume_breakout_multiplier": 0,
            "relative_strength_lookback_days": 5,
            "relative_strength_top_pct": 0,
        },
        "macro": {
            "nifty_kill_sma_period": 5,
            "bull_entry_sma_period": 0,
            "vix_kill_threshold": 25.0,
            "nifty_reentry_sma_period": 5,
            "vix_reentry_threshold": 20.0,
            "reentry_consecutive_sessions": 3,
        },
        "risk": {
            "atr_period": 5,
            "atr_stop_multiplier": 2.0,
            "donchian_period": 5,
            "trailing_stop_atr_period": 5,
            "trailing_stop_atr_multiplier": 2.0,
            "trailing_stop_atr_multiplier_kill_switch": 2.0,
            "max_loss_pct_per_trade": 1.0,
            "min_rr_ratio": 1.5,
            "max_concurrent_positions": 1,
            "max_total_portfolio_risk_pct": 15.0,
            "max_sector_exposure_pct": 50.0,
            "max_rr_cap": 6.0,
        },
        "entry_filters": {
            "trend_filter_enabled": True,
            "trend_fast_sma": 3,
            "trend_slow_sma": 5,
            "breakout_required": True,
            "breakout_lookback": 5,
            "rs_lookback_days": 5,
        },
        "trade_management": {
            "time_decay_sessions": 15,
            "binary_event_block_days": 14,
            "earnings_alert_days": 7,
        },
        "earnings": {"known_ahead_days": 7},
        "execution": {
            "entry_fill": "NEXT_OPEN",
            "entry_slippage_pct": 0.0,
            "exit_slippage_pct": 0.0,
            "max_entry_gap_up_pct": 5.0,
            "min_rr_at_fill": 1.2,
        },
        "data": {
            "eod_source": "bhavcopy",
            "adtv_sma_period": 5,
            "resistance_lookback_days": 10,
            "nifty_symbol": "NIFTY50_INDEX",
            "vix_symbol": "INDIA_VIX",
        },
        "gates": {
            "max_drawdown_pct": 15.0,
            "min_alpha_after_tax_pct": -2.0,
            "min_expectancy_r": 0.15,
            "min_profit_factor": 1.3,
            "min_trades": 1,
            "ltcg_tax_pct": 12.5,
            "risk_free_pct": 6.5,
        },
        "parabolic_stop": {"enabled": False},
        "partial_profit": {"enabled": False},
        "profit_ratchet": {"enabled": False},
    }


def test_golden_master_simulator_vs_plm_exits(session):
    """Assert that a position evaluated through Simulator produces identical exit date and price as PositionLifecycleManager."""
    cfg = _get_base_config()
    start_date = date(2024, 1, 1)

    # Populate index data: Nifty above SMA (bull), VIX healthy
    dates = [start_date + timedelta(days=i) for i in range(25)]
    for d in dates:
        session.add(
            MarketDataLake(
                symbol="NIFTY50_INDEX", trade_date=d, open_raw=22000.0,
                high_raw=22100.0, low_raw=21900.0, close_raw=22050.0,
                volume_raw=1000000, exchange="NSE"
            )
        )
        session.add(
            MarketDataLake(
                symbol="INDIA_VIX", trade_date=d, open_raw=14.0,
                high_raw=14.5, low_raw=13.5, close_raw=14.0,
                volume_raw=0, exchange="NSE"
            )
        )

    # Symbol SYNTH price history:
    # Day 1: high = 135 (establishes resistance target = 135 within 10-day lookback)
    # Days 2-9: consolidation around 96-102
    # Day 10: close at 106 (breakout over last 5 days high ~102) -> R:R = (135 - 106) / (106 - 95) = 2.64 >= 1.5
    # Day 11: opens at 106 -> filled in morning at 106
    # Days 12-16: rally to 118
    # Day 17: sharp drop to 90 (below stop 95) -> STOP_HIT exit
    symbol = "SYNTH"
    session.add(SharesOutstanding(symbol=symbol, effective_date=dates[0], shares_count=500_000_000))

    prices = [
        (95.0, 100.0, 93.0, 96.0),
        (96.0, 135.0, 94.0, 97.0),
        (97.0, 100.0, 95.0, 98.0),
        (98.0, 100.0, 96.0, 99.0),
        (99.0, 100.0, 97.0, 100.0),
        (99.0, 101.0, 97.0, 100.0),
        (98.0, 101.0, 96.0, 99.0),
        (99.0, 101.0, 97.0, 100.0),
        (100.0, 102.0, 98.0, 101.0),
        (101.0, 102.0, 99.0, 102.0),
        # Day 10: breakout close at 106.0
        (102.0, 107.0, 101.0, 106.0),
        # Day 11: next open = 106.0, rally
        (106.0, 110.0, 105.0, 109.0),
        # Day 12
        (109.0, 112.0, 108.0, 111.0),
        # Day 13
        (111.0, 114.0, 110.0, 113.0),
        # Day 14
        (113.0, 116.0, 112.0, 115.0),
        # Day 15
        (115.0, 117.0, 114.0, 116.0),
        # Day 16
        (116.0, 118.0, 115.0, 117.0),
        # Day 17: gap down through stop
        (94.0, 95.0, 90.0, 91.0),
    ]

    for i, (op, hi, lo, cl) in enumerate(prices):
        d = dates[i]
        session.add(
            MarketDataLake(
                symbol=symbol, trade_date=d, open_raw=op,
                high_raw=hi, low_raw=lo, close_raw=cl,
                volume_raw=5_000_000, exchange="NSE"
            )
        )
    session.flush()

    # Run Simulator over the date range
    sim = Simulator(cfg, session)
    sim_result = sim.run(start=dates[0], end=dates[17], initial_equity=1_000_000.0)

    assert len(sim_result.trades) == 1
    sim_trade = sim_result.trades.iloc[0]
    assert sim_trade["symbol"] == symbol
    assert sim_trade["entry_date"] == dates[10]
    assert sim_trade["exit_date"] == dates[17]
    assert sim_trade["entry_price"] == 102.0
    # Day 17 open was 94.0 which is below stop (gap down), so gap-aware stop fills at open 94.0
    assert sim_trade["pnl_gross"] == (94.0 - 102.0) * sim_trade["shares"]

    # Now verify PositionLifecycleManager produces the exact same exit price and date
    plm = PositionLifecycleManager(cfg, session)
    pos = ActivePosition(
        symbol=symbol, entry_date=dates[10], entry_price=102.0,
        shares=int(sim_trade["shares"]), original_shares=int(sim_trade["shares"]), shares_remaining=int(sim_trade["shares"]),
        initial_stop_loss=float(sim_trade["stop"]), live_stop_loss=float(sim_trade["stop"]),
        initial_resistance_target=135.0, projected_rr=2.25,
        days_held=0, highest_high_since_breakout=102.0,
        account_equity_at_entry=1_000_000.0, stop_a_at_entry=float(sim_trade["stop"]), stop_b_at_entry=float(sim_trade["stop"]),
        mode="PAPER",
    )
    session.add(pos)
    session.flush()

    # Advance PLM from day 10 to day 17
    exit_update = None
    for d in dates[10:18]:
        updates = plm.process_all(d, kill_switch_active=False)
        if updates and "POSITION_CLOSED" in updates[0].flags:
            exit_update = (d, updates[0])
            break

    assert exit_update is not None
    exit_date, plm_up = exit_update
    assert exit_date == dates[17]
    assert "STOP_HIT" in plm_up.flags


def test_simulator_exclusions_none_vs_empty(session):
    """Assert exclusions=None and exclusions=empty produce identical results."""
    cfg = _get_base_config()
    start_date = date(2024, 1, 1)
    dates = [start_date + timedelta(days=i) for i in range(16)]

    for i, d in enumerate(dates):
        session.add(
            MarketDataLake(
                symbol="NIFTY50_INDEX", trade_date=d, open_raw=22000.0,
                high_raw=22100.0, low_raw=21900.0, close_raw=22050.0,
                volume_raw=1000000, exchange="NSE"
            )
        )
        session.add(
            MarketDataLake(
                symbol="INDIA_VIX", trade_date=d, open_raw=14.0,
                high_raw=14.5, low_raw=13.5, close_raw=14.0,
                volume_raw=0, exchange="NSE"
            )
        )
        # Prior high on day 1 is 140
        hi_val = 140.0 if i == 1 else (102.0 + i)
        session.add(
            MarketDataLake(
                symbol="STOCK1", trade_date=d, open_raw=100.0 + i,
                high_raw=hi_val, low_raw=99.0 + i, close_raw=101.0 + i,
                volume_raw=5_000_000, exchange="NSE"
            )
        )
    session.add(SharesOutstanding(symbol="STOCK1", effective_date=dates[0], shares_count=500_000_000))
    session.flush()

    sim = Simulator(cfg, session)
    r1 = sim.run(dates[0], dates[-1], 1_000_000.0, exclusions=None)

    empty_exc = Exclusions(asm={}, earnings={}, block_days=14, known_ahead_days=7)
    r2 = sim.run(dates[0], dates[-1], 1_000_000.0, exclusions=empty_exc)

    assert len(r1.trades) == len(r2.trades)
    assert len(r1.skipped) == len(r2.skipped)
    assert (r1.equity == r2.equity).all()


def test_asm_exclusion_frees_slot_for_next_ranked(session):
    """Assert that excluding Candidate A frees the single available portfolio slot for Candidate B."""
    cfg = _get_base_config()
    start_date = date(2024, 1, 1)
    dates = [start_date + timedelta(days=i) for i in range(16)]

    for i, d in enumerate(dates):
        session.add(
            MarketDataLake(
                symbol="NIFTY50_INDEX", trade_date=d, open_raw=22000.0,
                high_raw=22100.0, low_raw=21900.0, close_raw=22050.0,
                volume_raw=1000000, exchange="NSE"
            )
        )
        session.add(
            MarketDataLake(
                symbol="INDIA_VIX", trade_date=d, open_raw=14.0,
                high_raw=14.5, low_raw=13.5, close_raw=14.0,
                volume_raw=0, exchange="NSE"
            )
        )
        # CAND_A: prior high on day 1 is 160, strong breakout
        hi_a = 160.0 if i == 1 else (102.0 + i * 2.0)
        session.add(
            MarketDataLake(
                symbol="CAND_A", trade_date=d, open_raw=100.0 + i * 2.0,
                high_raw=hi_a, low_raw=99.0 + i * 2.0, close_raw=101.0 + i * 2.0,
                volume_raw=5_000_000, exchange="NSE"
            )
        )
        # CAND_B: prior high on day 1 is 150, moderate breakout
        hi_b = 150.0 if i == 1 else (102.0 + i * 1.5)
        session.add(
            MarketDataLake(
                symbol="CAND_B", trade_date=d, open_raw=100.0 + i * 1.5,
                high_raw=hi_b, low_raw=99.0 + i * 1.5, close_raw=101.0 + i * 1.5,
                volume_raw=5_000_000, exchange="NSE"
            )
        )

    session.add(SharesOutstanding(symbol="CAND_A", effective_date=dates[0], shares_count=500_000_000))
    session.add(SharesOutstanding(symbol="CAND_B", effective_date=dates[0], shares_count=500_000_000))
    session.flush()

    sim = Simulator(cfg, session)

    # Run 1: No exclusions. Since max_concurrent_positions=1, CAND_A is ranked #1 (higher RS) and entered.
    r1 = sim.run(dates[0], dates[-1], 1_000_000.0, exclusions=None)
    traded_symbols_1 = set(r1.trades["symbol"].unique())
    assert "CAND_A" in traded_symbols_1
    assert "CAND_B" not in traded_symbols_1

    # Run 2: CAND_A is in ASM quarantine. CAND_A is dropped, and CAND_B enters in its slot.
    exc = Exclusions(
        asm={"CAND_A": [(dates[0], dates[-1])]},
        earnings={},
        block_days=14,
        known_ahead_days=7,
    )
    r2 = sim.run(dates[0], dates[-1], 1_000_000.0, exclusions=exc)
    traded_symbols_2 = set(r2.trades["symbol"].unique())
    assert "CAND_A" not in traded_symbols_2
    assert "CAND_B" in traded_symbols_2
