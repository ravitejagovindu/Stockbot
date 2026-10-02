"""
FInsight Trading Engine — Integration Test: Full EOD Pipeline

Tests the complete pipeline end-to-end with an in-memory database.
"""
from __future__ import annotations

import pytest
from datetime import date, timedelta

from data.db.models import MarketDataLake, SharesOutstanding, ActivePosition, PipelineRunLog
from live_runner.idempotency import IdempotencyGuard, AlreadyRunError


class TestIdempotencyGuard:
    """Test the idempotency guard in isolation."""

    def test_first_acquire_succeeds(self, db_session):
        guard = IdempotencyGuard(db_session)
        result = guard.acquire(date(2026, 10, 1))
        assert result is True

    def test_second_acquire_after_complete_returns_false(self, db_session):
        guard = IdempotencyGuard(db_session)
        guard.acquire(date(2026, 10, 1))
        guard.complete(date(2026, 10, 1), {"kill_switch_active": False})
        db_session.commit()

        result = guard.acquire(date(2026, 10, 1))
        assert result is False

    def test_acquire_after_failure_succeeds(self, db_session):
        guard = IdempotencyGuard(db_session)
        guard.acquire(date(2026, 10, 1))
        guard.fail(date(2026, 10, 1), "Test error")
        db_session.commit()

        result = guard.acquire(date(2026, 10, 1))
        assert result is True

    def test_different_dates_independent(self, db_session):
        guard = IdempotencyGuard(db_session)
        d1 = date(2026, 10, 1)
        d2 = date(2026, 10, 2)

        guard.acquire(d1)
        guard.complete(d1, {})
        db_session.commit()

        result = guard.acquire(d2)
        assert result is True

    def test_get_last_run_returns_latest(self, db_session):
        guard = IdempotencyGuard(db_session)
        d1 = date(2026, 9, 30)
        d2 = date(2026, 10, 1)

        guard.acquire(d1)
        guard.complete(d1, {"new_setups_generated": 3})
        guard.acquire(d2)
        guard.complete(d2, {"new_setups_generated": 5})
        db_session.commit()

        last = guard.get_last_run()
        assert last["run_date"] == str(d2)
        assert last["status"] == "COMPLETE"
        assert last["new_setups_generated"] == 5
