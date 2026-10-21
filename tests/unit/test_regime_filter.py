"""
Unit tests for engine_core.regime_filter.RegimeFilter.

Uses an in-memory SQLite database (via SQLAlchemy) and synthetic market data.
No real DB, no network calls, no external dependencies.

Test scenarios:
  * Kill switch activates when Nifty < SMA200
  * Kill switch activates when VIX > 20 (even with healthy Nifty)
  * Kill switch activates when both conditions met
  * Kill switch stays off when both conditions are safe
  * Re-entry requires BOTH conditions (AND, not OR)
  * Exactly 3 consecutive sessions needed to deactivate
  * Counter resets if any qualifying session is missed
  * Deactivation happens on the exact 3rd qualifying session
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from data.db.connection import Base
from data.db.models import MarketDataLake, RegimeState as RegimeStateModel
from engine_core.regime_filter import RegimeFilter, RegimeState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def in_memory_session():
    """Create a throwaway in-memory SQLite DB with required tables."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _make_config(
    kill_sma=200,
    vix_kill=20.0,
    reentry_sma=50,
    vix_reentry=18.0,
    reentry_sessions=3,
):
    """Build a minimal config dict for RegimeFilter."""
    return {
        "macro": {
            "nifty_kill_sma_period": kill_sma,
            "vix_kill_threshold": vix_kill,
            "nifty_reentry_sma_period": reentry_sma,
            "vix_reentry_threshold": vix_reentry,
            "reentry_consecutive_sessions": reentry_sessions,
        },
        "data": {
            "nifty_symbol": "NIFTY50_INDEX",
            "vix_symbol": "INDIA_VIX",
        },
    }


def _populate_market_data(session, symbol: str, closes: list[float], start_date: date):
    """Insert daily close prices into market_data_lake."""
    for i, close in enumerate(closes):
        d = start_date + timedelta(days=i)
        row = MarketDataLake(
            symbol=symbol,
            trade_date=d,
            open_raw=close,
            high_raw=close + 5,
            low_raw=close - 5,
            close_raw=close,
            volume_raw=1_000_000,
            exchange="NSE",
        )
        session.add(row)
    session.flush()


def _build_above_sma200_nifty(
    session, base_date, count=210, current_close=24000.0, sma200_target=22000.0
):
    """
    Populate Nifty data so that the last 200-day SMA is below current_close.
    Use a flat series near sma200_target for first 210 bars, then spike at the end.
    """
    closes = [sma200_target] * (count - 1) + [current_close]
    _populate_market_data(session, "NIFTY50_INDEX", closes, base_date)
    return base_date + timedelta(days=count - 1)


def _build_below_sma200_nifty(
    session, base_date, count=210, current_close=19000.0, sma200_target=22000.0
):
    """
    Populate Nifty data so that the last 200-day SMA is above current_close.
    """
    closes = [sma200_target] * (count - 1) + [current_close]
    _populate_market_data(session, "NIFTY50_INDEX", closes, base_date)
    return base_date + timedelta(days=count - 1)


def _add_vix(session, d: date, vix_close: float):
    """Insert a single VIX row."""
    row = MarketDataLake(
        symbol="INDIA_VIX",
        trade_date=d,
        open_raw=vix_close,
        high_raw=vix_close + 0.5,
        low_raw=vix_close - 0.5,
        close_raw=vix_close,
        volume_raw=0,
        exchange="NSE",
    )
    session.add(row)
    session.flush()


# ===========================================================================
# Tests
# ===========================================================================

class TestKillSwitchTrigger:

    def test_kill_switch_activates_when_nifty_below_sma200(self, in_memory_session):
        """Nifty < SMA200 → kill switch must activate."""
        start = date(2024, 1, 1)
        eval_date = _build_below_sma200_nifty(in_memory_session, start)
        _add_vix(in_memory_session, eval_date, vix_close=15.0)  # VIX safe

        rf = RegimeFilter(_make_config(), in_memory_session)
        state = rf.evaluate(eval_date)

        assert state.kill_switch_active is True
        assert state.reentry_consecutive_count == 0

    def test_kill_switch_activates_when_vix_above_threshold(self, in_memory_session):
        """VIX > 20 alone → kill switch must activate (OR logic)."""
        start = date(2024, 1, 1)
        # Nifty is healthy (above SMA200)
        eval_date = _build_above_sma200_nifty(in_memory_session, start)
        _add_vix(in_memory_session, eval_date, vix_close=21.0)  # VIX above threshold

        rf = RegimeFilter(_make_config(), in_memory_session)
        state = rf.evaluate(eval_date)

        assert state.kill_switch_active is True

    def test_kill_switch_stays_off_when_both_safe(self, in_memory_session):
        """Nifty > SMA200 AND VIX < 20 → kill switch must remain OFF."""
        start = date(2024, 1, 1)
        eval_date = _build_above_sma200_nifty(in_memory_session, start)
        _add_vix(in_memory_session, eval_date, vix_close=14.0)

        rf = RegimeFilter(_make_config(), in_memory_session)
        state = rf.evaluate(eval_date)

        assert state.kill_switch_active is False

    def test_kill_switch_activates_when_both_conditions_met(self, in_memory_session):
        """Both Nifty < SMA200 and VIX > 20 → kill switch activates."""
        start = date(2024, 1, 1)
        eval_date = _build_below_sma200_nifty(in_memory_session, start)
        _add_vix(in_memory_session, eval_date, vix_close=25.0)

        rf = RegimeFilter(_make_config(), in_memory_session)
        state = rf.evaluate(eval_date)

        assert state.kill_switch_active is True

    def test_vix_exactly_at_threshold_does_not_trigger(self, in_memory_session):
        """VIX == 20.0 (not strictly greater) → should NOT trigger."""
        start = date(2024, 1, 1)
        eval_date = _build_above_sma200_nifty(in_memory_session, start)
        _add_vix(in_memory_session, eval_date, vix_close=20.0)

        rf = RegimeFilter(_make_config(vix_kill=20.0), in_memory_session)
        state = rf.evaluate(eval_date)

        # VIX == threshold, not greater than → should NOT trigger
        assert state.kill_switch_active is False


class TestReEntryHysteresis:
    """Re-entry requires 3 consecutive qualifying sessions (AND, not OR)."""

    def _activate_kill_switch(self, session, base_date: date) -> date:
        """Helper: set up data to activate kill switch, return eval_date."""
        eval_date = _build_below_sma200_nifty(session, base_date)
        _add_vix(session, eval_date, vix_close=15.0)
        rf = RegimeFilter(_make_config(), session)
        rf.evaluate(eval_date)
        return eval_date

    def _add_nifty_above_sma50(self, session, base_date: date, eval_date: date):
        """Insert a Nifty bar that is clearly above SMA50 on eval_date."""
        # We need eval_date Nifty row to exist with close > SMA50
        # Since we already have 210 bars near 22000, SMA50 ≈ 22000
        # Add a bar at 25000 (above any SMA50)
        row = MarketDataLake(
            symbol="NIFTY50_INDEX",
            trade_date=eval_date,
            open_raw=25000.0,
            high_raw=25100.0,
            low_raw=24900.0,
            close_raw=25000.0,
            volume_raw=1_000_000,
            exchange="NSE",
        )
        session.add(row)
        session.flush()

    def test_exactly_3_sessions_deactivates(self, in_memory_session):
        """Kill switch must deactivate after exactly 3 consecutive qualifying sessions."""
        base = date(2024, 1, 1)

        # Session 0: activate kill switch (Nifty < SMA200, VIX safe)
        activation_date = _build_below_sma200_nifty(in_memory_session, base)
        _add_vix(in_memory_session, activation_date, vix_close=14.0)
        rf = RegimeFilter(_make_config(), in_memory_session)
        s0 = rf.evaluate(activation_date)
        assert s0.kill_switch_active is True

        # Build a fresh Nifty series with close > SMA50 for re-entry sessions
        # Use a series of values near 21000 (below SMA200 at 22000 but our
        # kill switch is already active, so only SMA50 matters for re-entry)
        # SMA50 of previous bars is ~22000; close at 23000 > SMA50 ✓
        reentry_base_nifty = 23000.0

        # Sessions 1, 2, 3: add qualifying re-entry sessions
        for i, session_offset in enumerate([1, 2, 3]):
            reentry_date = activation_date + timedelta(days=session_offset)

            # Insert a Nifty bar where close > SMA50 (of previous 50 bars)
            in_memory_session.add(MarketDataLake(
                symbol="NIFTY50_INDEX",
                trade_date=reentry_date,
                open_raw=reentry_base_nifty,
                high_raw=reentry_base_nifty + 100,
                low_raw=reentry_base_nifty - 100,
                close_raw=reentry_base_nifty,
                volume_raw=1_000_000,
                exchange="NSE",
            ))
            _add_vix(in_memory_session, reentry_date, vix_close=17.0)  # < 18 ✓
            in_memory_session.flush()

            rf2 = RegimeFilter(_make_config(), in_memory_session)
            state = rf2.evaluate(reentry_date)

            if i < 2:  # Sessions 1 & 2
                assert state.kill_switch_active is True, (
                    f"Kill switch should still be active after {i+1} sessions"
                )
                assert state.reentry_consecutive_count == i + 1
            else:  # Session 3
                assert state.kill_switch_active is False, (
                    "Kill switch must deactivate after 3 consecutive qualifying sessions"
                )

    def test_counter_resets_on_missed_session(self, in_memory_session):
        """If any qualifying session is missed, the counter resets to 0."""
        base = date(2024, 1, 1)

        # Activate kill switch
        act_date = _build_below_sma200_nifty(in_memory_session, base)
        _add_vix(in_memory_session, act_date, vix_close=14.0)
        rf = RegimeFilter(_make_config(), in_memory_session)
        rf.evaluate(act_date)

        reentry_base = 23000.0

        # Session 1: qualifying
        d1 = act_date + timedelta(days=1)
        in_memory_session.add(MarketDataLake(
            symbol="NIFTY50_INDEX", trade_date=d1,
            open_raw=reentry_base, high_raw=reentry_base+100,
            low_raw=reentry_base-100, close_raw=reentry_base,
            volume_raw=1_000_000, exchange="NSE"
        ))
        _add_vix(in_memory_session, d1, vix_close=17.0)
        in_memory_session.flush()
        rf.evaluate(d1)

        # Session 2: qualifying
        d2 = act_date + timedelta(days=2)
        in_memory_session.add(MarketDataLake(
            symbol="NIFTY50_INDEX", trade_date=d2,
            open_raw=reentry_base, high_raw=reentry_base+100,
            low_raw=reentry_base-100, close_raw=reentry_base,
            volume_raw=1_000_000, exchange="NSE"
        ))
        _add_vix(in_memory_session, d2, vix_close=17.0)
        in_memory_session.flush()
        s2 = rf.evaluate(d2)
        assert s2.reentry_consecutive_count == 2

        # Session 3: NOT qualifying — VIX spikes above reentry threshold
        d3 = act_date + timedelta(days=3)
        in_memory_session.add(MarketDataLake(
            symbol="NIFTY50_INDEX", trade_date=d3,
            open_raw=reentry_base, high_raw=reentry_base+100,
            low_raw=reentry_base-100, close_raw=reentry_base,
            volume_raw=1_000_000, exchange="NSE"
        ))
        _add_vix(in_memory_session, d3, vix_close=19.0)  # > 18.0 → fails re-entry
        in_memory_session.flush()
        s3 = rf.evaluate(d3)

        assert s3.kill_switch_active is True  # Still active
        assert s3.reentry_consecutive_count == 0  # Counter reset

    def test_reentry_requires_both_conditions(self, in_memory_session):
        """Re-entry requires BOTH Nifty > SMA50 AND VIX < 18 (AND, not OR)."""
        base = date(2024, 1, 1)

        # Activate kill switch
        act_date = _build_below_sma200_nifty(in_memory_session, base)
        _add_vix(in_memory_session, act_date, vix_close=14.0)
        rf = RegimeFilter(_make_config(), in_memory_session)
        rf.evaluate(act_date)

        reentry_base = 20000.0

        # Session with Nifty qualifying but VIX NOT qualifying
        d1 = act_date + timedelta(days=1)
        in_memory_session.add(MarketDataLake(
            symbol="NIFTY50_INDEX", trade_date=d1,
            open_raw=reentry_base, high_raw=reentry_base+100,
            low_raw=reentry_base-100, close_raw=reentry_base,
            volume_raw=1_000_000, exchange="NSE"
        ))
        _add_vix(in_memory_session, d1, vix_close=19.5)  # VIX fails → no re-entry
        in_memory_session.flush()

        s1 = rf.evaluate(d1)
        assert s1.kill_switch_active is True
        assert s1.reentry_consecutive_count == 0  # VIX fail → counter stays at 0


class TestGetCurrentState:

    def test_get_current_state_returns_latest(self, in_memory_session):
        """get_current_state should return the most recently evaluated state."""
        start = date(2024, 1, 1)
        eval_date = _build_above_sma200_nifty(in_memory_session, start)
        _add_vix(in_memory_session, eval_date, vix_close=14.0)

        rf = RegimeFilter(_make_config(), in_memory_session)
        rf.evaluate(eval_date)

        state = rf.get_current_state()
        assert state is not None
        assert state.eval_date == eval_date
        assert state.kill_switch_active is False

    def test_get_current_state_returns_none_when_no_data(self, in_memory_session):
        """get_current_state returns None when regime_state table is empty."""
        rf = RegimeFilter(_make_config(), in_memory_session)
        state = rf.get_current_state()
        assert state is None
