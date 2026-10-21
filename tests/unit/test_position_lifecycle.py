"""
Unit tests for engine_core.position_lifecycle.PositionLifecycleManager.

Uses in-memory SQLite — no real DB, no network, no mocks needed for the
state machine logic.

Test scenarios:
  * Position hits 1:1 on day 5 → transitions to RISK_FREE_1_TO_1
  * Position never hits 1:1 in 15 days → PENDING_MANUAL_EXIT on day 15
  * Position hits 1:1 on day 14 → NOT flagged as PENDING_MANUAL_EXIT
    (graduation takes priority)
  * Trailing stop only ratchets UP (never down)
  * Earnings alert fires at exactly 7 days and at 1 day
  * Earnings alert is independent of position state (fires in any state)
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.db.connection import Base
from data.db.models import (
    ActivePosition,
    EarningsCalendar,
    MarketDataLake,
    CorporateActionsLog,
)
from engine_core.position_lifecycle import PositionLifecycleManager, PositionState


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()
    engine.dispose()


def _config(time_decay=15, earnings_alert=7, atr_period=14, trailing_mult=2.0, mode="PAPER"):
    return {
        "runtime": {
            "mode": mode,
            "paper_start_equity": 1_000_000.0,
        },
        "risk": {
            "atr_period": atr_period,
            "trailing_stop_atr_multiplier": trailing_mult,
            "trailing_stop_atr_multiplier_kill_switch": 2.0,
            "max_loss_pct_per_trade": 1.0,
        },
        "trade_management": {
            "time_decay_sessions": time_decay,
            "earnings_alert_days": earnings_alert,
        },
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
        "execution": {
            "exit_slippage_pct": 0.0,
            "entry_slippage_pct": 0.1,
            "max_entry_gap_up_pct": 3.0,
            "min_rr_at_fill": 1.5,
        },
    }


def _add_position(
    session,
    symbol="TEST",
    entry_date=date(2024, 1, 2),
    entry_price=100.0,
    initial_stop=90.0,
    initial_resistance=120.0,
    shares=10,
    days_held=0,
    highest_high=100.0,
    state="INITIAL_RISK",
    live_stop=90.0,
    sector=None,
    mode="PAPER",
) -> int:
    """Insert an ActivePosition and return its ID."""
    pos = ActivePosition(
        symbol=symbol,
        entry_date=entry_date,
        entry_price=entry_price,
        shares=shares,
        original_shares=shares,
        shares_remaining=shares,
        initial_stop_loss=initial_stop,
        live_stop_loss=live_stop,
        initial_resistance_target=initial_resistance,
        projected_rr=2.0,
        position_state=state,
        days_held=days_held,
        highest_high_since_breakout=highest_high,
        sector=sector,
        earnings_alert=False,
        account_equity_at_entry=100_000.0,
        stop_a_at_entry=initial_stop,
        stop_b_at_entry=initial_stop,
        mode=mode,
    )
    session.add(pos)
    session.flush()
    return pos.id


def _add_ohlcv(session, symbol, trade_date, high, low=None, close=None, open_=None):
    """Insert a single OHLCV bar."""
    close = close or high - 2
    low = low or high - 5
    open_ = open_ or high - 3
    row = MarketDataLake(
        symbol=symbol,
        trade_date=trade_date,
        open_raw=open_,
        high_raw=high,
        low_raw=low,
        close_raw=close,
        volume_raw=500_000,
        exchange="NSE",
    )
    session.add(row)
    session.flush()


def _add_many_ohlcv(session, symbol, start_date, n, high=105.0, low=95.0, close=100.0):
    """Add n consecutive OHLCV bars with constant prices."""
    for i in range(n):
        d = start_date + timedelta(days=i)
        _add_ohlcv(session, symbol, d, high=high, low=low, close=close)


def _add_earnings(session, symbol, event_date):
    ec = EarningsCalendar(
        symbol=symbol,
        event_date=event_date,
        event_type="EARNINGS",
        source="test",
    )
    session.add(ec)
    session.flush()


# ===========================================================================
# State machine: INITIAL_RISK → RISK_FREE_1_TO_1
# ===========================================================================

class TestInitialRiskGraduation:

    def test_hits_1_to_1_on_day_5_transitions_to_risk_free(self, session):
        """Position that reaches 1:1 on day 5 must graduate to RISK_FREE_1_TO_1."""
        symbol = "GRADTEST"
        entry_date = date(2024, 1, 2)
        entry_price = 100.0
        stop = 90.0  # 1R = 10

        # Add 14 + 5 historical bars (need enough for ATR)
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)

        # Day 5 bar: high reaches entry + 1R + epsilon = 110.5
        eval_date = date(2024, 1, 6)  # 5th day
        _add_ohlcv(session, symbol, eval_date, high=111.0, low=95.0, close=108.0)

        pos_id = _add_position(
            session, symbol=symbol,
            entry_date=entry_date, entry_price=entry_price,
            initial_stop=stop, live_stop=stop,
            days_held=4, highest_high=105.0,  # hasn't hit 1:1 yet
            state="INITIAL_RISK",
        )

        mgr = PositionLifecycleManager(_config(), session)
        update = mgr.process_single(pos_id, eval_date)

        assert update.new_state == PositionState.RISK_FREE_1_TO_1
        # Live stop moves to breakeven (entry price)
        assert update.new_live_stop_loss == pytest.approx(100.0)
        assert "STATE_CHANGED" in update.flags

    def test_live_stop_set_to_entry_on_graduation(self, session):
        """When graduating to RISK_FREE_1_TO_1, live_stop_loss must equal entry_price."""
        symbol = "BEVEN"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 6)
        _add_ohlcv(session, symbol, eval_date, high=115.0, low=95.0, close=112.0)

        pos_id = _add_position(session, symbol=symbol, entry_price=100.0,
                               initial_stop=90.0, live_stop=90.0, days_held=4,
                               highest_high=105.0, state="INITIAL_RISK")
        mgr = PositionLifecycleManager(_config(), session)
        update = mgr.process_single(pos_id, eval_date)
        assert update.new_live_stop_loss == pytest.approx(100.0)  # = entry_price


# ===========================================================================
# State machine: time-decay → PENDING_MANUAL_EXIT
# ===========================================================================

class TestTimedecayPendingManualExit:

    def test_no_graduation_in_15_days_triggers_pending(self, session):
        """Never hitting 1:1 in 15 sessions flags time-decay, then exits at next open."""
        symbol = "DECAYTEST"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 16)
        _add_ohlcv(session, symbol, eval_date, high=105.0, low=95.0, close=100.0)

        pos_id = _add_position(
            session, symbol=symbol,
            entry_price=100.0, initial_stop=90.0, live_stop=90.0,
            days_held=14,  # This run pushes it to 15
            highest_high=105.0,  # Never reached 110 (entry + 1R)
            state="INITIAL_RISK",
        )
        mgr = PositionLifecycleManager(_config(time_decay=15), session)
        update = mgr.process_single(pos_id, eval_date)
        assert update.new_state == PositionState.PENDING_MANUAL_EXIT
        assert "TIME_DECAY_FLAGGED" in update.flags
        assert "STATE_CHANGED" in update.flags
        assert session.get(ActivePosition, pos_id) is not None

        # Next session (day 16): exits at open
        next_date = date(2024, 1, 17)
        _add_ohlcv(session, symbol, next_date, high=102.0, low=99.0, close=100.0, open_=101.0)
        update2 = mgr.process_single(pos_id, next_date)
        assert update2.new_state == PositionState.CLOSED
        assert "TIME_DECAY_EXIT" in update2.flags
        assert "POSITION_CLOSED" in update2.flags
        assert session.get(ActivePosition, pos_id) is None

    def test_hits_1r_on_day_14_not_flagged_as_pending(self, session):
        """Graduating to RISK_FREE on day 14 takes priority over PENDING_MANUAL_EXIT."""
        symbol = "DAY14GRAD"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 15)
        # High on day 14 = 112 — exactly crosses entry(100) + 1R(10) + buffer
        _add_ohlcv(session, symbol, eval_date, high=112.0, low=95.0, close=110.0)

        pos_id = _add_position(
            session, symbol=symbol,
            entry_price=100.0, initial_stop=90.0, live_stop=90.0,
            days_held=13,  # After this run: days_held = 14
            highest_high=108.0,
            state="INITIAL_RISK",
        )
        mgr = PositionLifecycleManager(_config(time_decay=15), session)
        update = mgr.process_single(pos_id, eval_date)

        # Must graduate to RISK_FREE, not PENDING_MANUAL_EXIT
        assert update.new_state == PositionState.RISK_FREE_1_TO_1
        assert update.new_state != PositionState.PENDING_MANUAL_EXIT
        assert update.new_state != PositionState.CLOSED

    def test_exactly_on_day_15_triggers_pending_if_no_graduation(self, session):
        """Day 15 exactly is the trigger boundary — must flag on day 15 and exit next open."""
        symbol = "EXACT15"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 16)
        _add_ohlcv(session, symbol, eval_date, high=104.0, low=94.0, close=101.0)

        pos_id = _add_position(
            session, symbol=symbol,
            entry_price=100.0, initial_stop=90.0, live_stop=90.0,
            days_held=14,  # Will become 15 after this run
            highest_high=104.0,  # Never hit 110
            state="INITIAL_RISK",
        )
        mgr = PositionLifecycleManager(_config(time_decay=15), session)
        update = mgr.process_single(pos_id, eval_date)
        assert update.new_days_held == 15
        assert update.new_state == PositionState.PENDING_MANUAL_EXIT
        assert "TIME_DECAY_FLAGGED" in update.flags

        # Next session: exits at open
        next_date = date(2024, 1, 17)
        _add_ohlcv(session, symbol, next_date, high=102.0, low=98.0, close=100.0, open_=99.0)
        update2 = mgr.process_single(pos_id, next_date)
        assert update2.new_state == PositionState.CLOSED
        assert "TIME_DECAY_EXIT" in update2.flags
        assert session.get(ActivePosition, pos_id) is None

    def test_stop_loss_hit_triggers_automated_exit(self, session):
        """When low <= live_stop_loss, position automatically closes as STOP_HIT without manual confirmation."""
        symbol = "STOPTEST"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 16)
        _add_ohlcv(session, symbol, eval_date, high=102.0, low=88.0, close=91.0)

        pos_id = _add_position(
            session, symbol=symbol,
            entry_price=100.0, initial_stop=90.0, live_stop=90.0,
            days_held=5,
            highest_high=105.0,
            state="INITIAL_RISK",
        )
        mgr = PositionLifecycleManager(_config(), session)
        update = mgr.process_single(pos_id, eval_date)

        assert update.new_state == PositionState.CLOSED
        assert "STOP_HIT" in update.flags
        assert "POSITION_CLOSED" in update.flags
        assert session.get(ActivePosition, pos_id) is None


# ===========================================================================
# State machine: RISK_FREE_1_TO_1 → TRAILING_ATR
# ===========================================================================

class TestRiskFreeToTrailing:

    def test_above_resistance_transitions_to_trailing_atr(self, session):
        """Exceeding resistance target while RISK_FREE transitions to TRAILING_ATR."""
        symbol = "TRAILTEST"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=110.0, low=95.0, close=105.0)
        eval_date = date(2024, 1, 10)
        # High exceeds resistance target (120.0)
        _add_ohlcv(session, symbol, eval_date, high=125.0, low=105.0, close=122.0)

        pos_id = _add_position(
            session, symbol=symbol,
            entry_price=100.0, initial_stop=90.0, live_stop=100.0,
            initial_resistance=120.0,
            days_held=8, highest_high=115.0,
            state="RISK_FREE_1_TO_1",
        )
        mgr = PositionLifecycleManager(_config(), session)
        update = mgr.process_single(pos_id, eval_date)
        assert update.new_state == PositionState.TRAILING_ATR


# ===========================================================================
# Trailing stop: ratchet-only-up
# ===========================================================================

class TestTrailingStopRatchet:

    def test_trailing_stop_never_goes_down(self, session):
        """Trailing stop should only ratchet UP — never move down if ATR widens."""
        symbol = "RATCHET"
        # 30 bars with high volatility (high=120, low=80 → ATR≈40)
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=120.0, low=80.0, close=100.0)

        # Current session: low volatility breakout
        eval_date = date(2024, 1, 10)
        _add_ohlcv(session, symbol, eval_date, high=130.0, low=125.0, close=128.0)

        # Set a high live_stop from previous run (simulated already-ratcheted stop)
        existing_live_stop = 115.0

        pos_id = _add_position(
            session, symbol=symbol,
            entry_price=100.0, initial_stop=90.0, live_stop=existing_live_stop,
            days_held=30, highest_high=125.0,
            state="TRAILING_ATR",
        )

        mgr = PositionLifecycleManager(_config(trailing_mult=2.0), session)
        update = mgr.process_single(pos_id, eval_date)

        # Trailing stop must never be less than existing_live_stop
        assert update.new_live_stop_loss >= existing_live_stop

    def test_trailing_stop_moves_up_when_candidate_is_higher(self, session):
        """Trailing stop must update upward when candidate_stop > current live_stop."""
        symbol = "UPTRAIL"
        # Flat ATR around 5 (high=105, low=95 → TR=10, ATR ≈ 10)
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 10)
        _add_ohlcv(session, symbol, eval_date, high=140.0, low=135.0, close=138.0)

        pos_id = _add_position(
            session, symbol=symbol,
            entry_price=100.0, initial_stop=90.0, live_stop=100.0,
            days_held=20, highest_high=135.0,
            state="TRAILING_ATR",
        )
        mgr = PositionLifecycleManager(_config(trailing_mult=2.0), session)
        update = mgr.process_single(pos_id, eval_date)

        # candidate_stop = new_highest_high - 2*ATR
        # new_highest_high = max(135, 140) = 140
        # ATR ≈ 10, so candidate_stop ≈ 140 - 20 = 120
        # live_stop was 100, so it should move to ≈ 120
        assert update.new_live_stop_loss > 100.0


# ===========================================================================
# Earnings alert
# ===========================================================================

class TestEarningsAlert:

    def test_alert_fires_at_exactly_7_days(self, session):
        """Earnings alert must fire when event is exactly 7 calendar days away."""
        symbol = "ALERTTEST"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 10)
        _add_ohlcv(session, symbol, eval_date, high=105.0, low=95.0, close=100.0)

        # Event exactly 7 days from eval_date
        event_date = eval_date + timedelta(days=7)
        _add_earnings(session, symbol, event_date)

        pos_id = _add_position(session, symbol=symbol, days_held=2, state="INITIAL_RISK")
        mgr = PositionLifecycleManager(_config(earnings_alert=7), session)
        update = mgr.process_single(pos_id, eval_date)

        assert update.earnings_alert is True
        assert "EARNINGS_ALERT" in update.flags

    def test_alert_fires_at_1_day(self, session):
        """Earnings alert must still fire when event is only 1 day away."""
        symbol = "IMMINENT"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 10)
        _add_ohlcv(session, symbol, eval_date, high=105.0, low=95.0, close=100.0)

        _add_earnings(session, symbol, eval_date + timedelta(days=1))

        pos_id = _add_position(session, symbol=symbol, days_held=5, state="RISK_FREE_1_TO_1",
                               live_stop=100.0)
        mgr = PositionLifecycleManager(_config(earnings_alert=7), session)
        update = mgr.process_single(pos_id, eval_date)

        assert update.earnings_alert is True

    def test_alert_independent_of_state_trailing_atr(self, session):
        """Earnings alert must fire even when position is in TRAILING_ATR state."""
        symbol = "TRAILING_EARNS"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 10)
        _add_ohlcv(session, symbol, eval_date, high=105.0, low=95.0, close=100.0)

        _add_earnings(session, symbol, eval_date + timedelta(days=3))

        pos_id = _add_position(session, symbol=symbol, days_held=20, state="TRAILING_ATR",
                               live_stop=100.0)
        mgr = PositionLifecycleManager(_config(earnings_alert=7), session)
        update = mgr.process_single(pos_id, eval_date)

        assert update.earnings_alert is True

    def test_no_alert_when_event_beyond_threshold(self, session):
        """No alert when the next event is beyond the alert window."""
        symbol = "FAR_EARNS"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 10)
        _add_ohlcv(session, symbol, eval_date, high=105.0, low=95.0, close=100.0)

        _add_earnings(session, symbol, eval_date + timedelta(days=30))  # Far away

        pos_id = _add_position(session, symbol=symbol, days_held=3, state="INITIAL_RISK")
        mgr = PositionLifecycleManager(_config(earnings_alert=7), session)
        update = mgr.process_single(pos_id, eval_date)

        assert update.earnings_alert is False
        assert "EARNINGS_ALERT" not in update.flags

    def test_no_alert_when_no_event_in_db(self, session):
        """No alert when there are no earnings events in the calendar."""
        symbol = "NO_EARNS"
        _add_many_ohlcv(session, symbol, date(2023, 12, 1), n=30,
                        high=105.0, low=95.0, close=100.0)
        eval_date = date(2024, 1, 10)
        _add_ohlcv(session, symbol, eval_date, high=105.0, low=95.0, close=100.0)

        # No earnings inserted
        pos_id = _add_position(session, symbol=symbol, days_held=3, state="INITIAL_RISK")
        mgr = PositionLifecycleManager(_config(earnings_alert=7), session)
        update = mgr.process_single(pos_id, eval_date)

        assert update.earnings_alert is False


# ===========================================================================
# Step-Lock Profit Ratchet Tests
# ===========================================================================

class TestProfitRatchet:

    def test_locks_1r_at_2r(self, session):
        """When highest high reaches +2R, stop is locked at +1R."""
        symbol = "RATCHET_2R"
        entry_date = date(2024, 1, 2)
        entry_price = 100.0
        stop = 90.0  # 1R = 10, so +2R = 120, locked stop = 110 (+1R)

        _add_many_ohlcv(session, symbol, entry_date, n=20, high=105.0, low=95.0, close=100.0)
        eval_date = entry_date + timedelta(days=20)
        # Today hits 122 (> 120 = +2R)
        _add_ohlcv(session, symbol, eval_date, high=122.0, low=115.0, close=118.0)

        pos_id = _add_position(
            session,
            symbol=symbol,
            entry_date=entry_date,
            entry_price=entry_price,
            initial_stop=stop,
            live_stop=100.0,
            initial_resistance=150.0,
            state="RISK_FREE_1_TO_1",
            highest_high=112.0,
        )

        cfg = _config()
        cfg["profit_ratchet"] = {
            "enabled": True,
            "rungs": [
                {"trigger_rr": 1.0, "lock_rr": 0.0},
                {"trigger_rr": 2.0, "lock_rr": 1.0},
                {"trigger_rr": 3.0, "lock_rr": 2.0},
            ],
        }

        mgr = PositionLifecycleManager(cfg, session)
        update = mgr.process_single(pos_id, eval_date)

        # 1R = 10. +1R lock = 100 + 10 = 110.0
        assert update.new_live_stop_loss >= 110.0

    def test_locks_2r_at_3r(self, session):
        """When highest high reaches +3R, stop is locked at +2R."""
        symbol = "RATCHET_3R"
        entry_date = date(2024, 1, 2)
        entry_price = 100.0
        stop = 90.0  # 1R = 10, so +3R = 130, locked stop = 120 (+2R)

        _add_many_ohlcv(session, symbol, entry_date, n=20, high=105.0, low=95.0, close=100.0)
        eval_date = entry_date + timedelta(days=20)
        # Today hits 132 (> 130 = +3R)
        _add_ohlcv(session, symbol, eval_date, high=132.0, low=125.0, close=128.0)

        pos_id = _add_position(
            session,
            symbol=symbol,
            entry_date=entry_date,
            entry_price=entry_price,
            initial_stop=stop,
            live_stop=110.0,
            initial_resistance=150.0,
            state="RISK_FREE_1_TO_1",
            highest_high=122.0,
        )

        cfg = _config()
        cfg["profit_ratchet"] = {
            "enabled": True,
            "rungs": [
                {"trigger_rr": 1.0, "lock_rr": 0.0},
                {"trigger_rr": 2.0, "lock_rr": 1.0},
                {"trigger_rr": 3.0, "lock_rr": 2.0},
            ],
        }

        mgr = PositionLifecycleManager(cfg, session)
        update = mgr.process_single(pos_id, eval_date)

        # 1R = 10. +2R lock = 100 + 20 = 120.0
        assert update.new_live_stop_loss >= 120.0

    def test_ratchet_bypassed_when_regime_not_enabled(self, session):
        """When enabled_regimes is set and market is in bull regime, ratchet is bypassed."""
        from data.db.models import RegimeState as DBRegimeState
        symbol = "RATCHET_BYPASS"
        entry_date = date(2024, 1, 2)
        entry_price = 100.0
        stop = 90.0

        _add_many_ohlcv(session, symbol, entry_date, n=20, high=105.0, low=95.0, close=100.0)
        eval_date = entry_date + timedelta(days=20)
        _add_ohlcv(session, symbol, eval_date, high=122.0, low=115.0, close=118.0)

        # Record a confirmed bull regime in regime_state
        r_state = DBRegimeState(
            eval_date=eval_date,
            nifty_close=20000.0,
            nifty_sma200=18000.0,
            nifty_sma50=19500.0,
            vix_close=14.0,
            kill_switch_active=False,
            reentry_consecutive_count=0,
        )
        session.add(r_state)
        session.flush()

        pos_id = _add_position(
            session,
            symbol=symbol,
            entry_date=entry_date,
            entry_price=entry_price,
            initial_stop=stop,
            live_stop=100.0,
            initial_resistance=150.0,
            state="RISK_FREE_1_TO_1",
            highest_high=112.0,
        )

        cfg = _config()
        cfg["profit_ratchet"] = {
            "enabled": True,
            "active_in_bull": False,  # Not active in bull
            "rungs": [
                {"trigger_rr": 1.0, "lock_rr": 0.0},
                {"trigger_rr": 2.0, "lock_rr": 1.0},
                {"trigger_rr": 3.0, "lock_rr": 2.0},
            ],
        }

        mgr = PositionLifecycleManager(cfg, session)
        update = mgr.process_single(pos_id, eval_date)

        # Stop should remain at 100.0 (breakeven), NOT ratcheted to 110.0 (+1R)
        assert update.new_live_stop_loss == 100.0
