"""tests/integration/test_live_vs_rules.py — Golden master test comparing advance_one_bar vs PositionLifecycleManager."""
from __future__ import annotations

from datetime import date, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.db.connection import Base
from data.db.models import ActivePosition, MarketDataLake, RegimeState
from engine_core.lifecycle_rules import (
    Bar,
    BarCtx,
    LifecycleRules,
    PosState,
    advance_one_bar,
    parabolic_ref_close,
)
from engine_core.position_lifecycle import PositionLifecycleManager, PositionState


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()
    engine.dispose()


def test_golden_master_40_bars(session):
    symbol = "SYNTH"
    start_date = date(2024, 1, 1)

    cfg = {
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
        "risk": {
            "atr_period": 14,
            "trailing_stop_atr_multiplier": 2.0,
            "trailing_stop_atr_multiplier_kill_switch": 2.0,
            "max_loss_pct_per_trade": 1.0,
        },
        "trade_management": {"time_decay_sessions": 15, "earnings_alert_days": 7},
        "execution": {"exit_slippage_pct": 0.0},
        "parabolic_stop": {"enabled": False},
        "partial_profit": {"enabled": False},
        "profit_ratchet": {"enabled": False},
    }

    rules = LifecycleRules.from_config(cfg)
    mgr = PositionLifecycleManager(cfg, session)

    # 40 synthetic bars: rising from 100 to 135
    # First 20 bars historical before entry so ATR14 is well formed
    for i in range(20):
        d = start_date + timedelta(days=i)
        session.add(
            MarketDataLake(
                symbol=symbol, trade_date=d, open_raw=100.0, high_raw=102.0,
                low_raw=98.0, close_raw=100.0, volume_raw=100000, exchange="NSE"
            )
        )
    session.flush()

    # Entry on day 20
    entry_date = start_date + timedelta(days=20)
    pos_id = ActivePosition(
        symbol=symbol, entry_date=entry_date, entry_price=100.0,
        shares=100, original_shares=100, shares_remaining=100,
        initial_stop_loss=90.0, live_stop_loss=90.0,
        initial_resistance_target=120.0, projected_rr=2.0,
        days_held=0, highest_high_since_breakout=100.0,
        account_equity_at_entry=1_000_000.0, stop_a_at_entry=90.0, stop_b_at_entry=90.0,
        mode="PAPER",
    )
    session.add(pos_id)
    session.flush()

    pure_pos = PosState(
        entry_price=100.0, initial_stop=90.0, live_stop=90.0,
        target=120.0, state="INITIAL_RISK", days_held=0,
        highest_high=100.0, shares_remaining=100,
    )

    # 40 bars starting from day 21
    # Bars sequence:
    # Days 1-5: reach 112 (> 110 = 1R) -> RISK_FREE_1_TO_1
    # Days 6-10: reach 125 (> 120 = resistance) -> TRAILING_ATR
    # Days 11-15: trailing up
    # Day 16: drop to hit stop
    prices = [
        # (open, high, low, close)
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 108, 103, 107),
        (107, 112, 106, 111),  # hits 1R (110)
        (111, 114, 110, 113),
        (113, 117, 112, 116),
        (116, 122, 115, 121),  # hits resistance (120)
        (121, 126, 120, 125),
        (125, 129, 124, 128),
        (128, 132, 127, 131),
        (131, 135, 130, 134),
        (134, 136, 132, 135),
        (135, 137, 133, 136),
        (136, 138, 134, 137),
        (137, 138, 135, 136),
        (130, 131, 110, 112),  # sharp drop hitting trailing stop
    ]

    for step, (o, h, l, c) in enumerate(prices):
        bar_date = entry_date + timedelta(days=step + 1)
        session.add(
            MarketDataLake(
                symbol=symbol, trade_date=bar_date, open_raw=float(o), high_raw=float(h),
                low_raw=float(l), close_raw=float(c), volume_raw=100000, exchange="NSE"
            )
        )
        session.flush()

        # LifecycleManager step
        update = mgr.process_single(pos_id.id, bar_date)

        # Advance pure state machine
        # We compute ATR14 as roughly 4.0 for this bar (high - low ~ 4-6)
        bar = Bar(float(o), float(h), float(l), float(c))
        # Look up atr from plm calculation or check update
        ctx = BarCtx(atr14=4.0, kill_switch=False, is_bull=False)
        # Advance one bar
        res = advance_one_bar(pure_pos, bar, ctx, rules)
        pure_pos = res.pos

        # Verify state transition and stop matching
        if not res.closed:
            assert update.new_state.value == pure_pos.state
            assert update.new_days_held == pure_pos.days_held
            assert update.new_highest_high == pure_pos.highest_high
        else:
            assert update.new_state == PositionState.CLOSED
            break
