"""
FInsight Trading Engine — Idempotency Guard

Prevents the EOD pipeline from running more than once per trading day.
Uses the pipeline_run_log table with a DB-level UNIQUE constraint on run_date.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from data.db.models import PipelineRunLog

logger = logging.getLogger(__name__)


class AlreadyRunError(Exception):
    """Raised when today's pipeline has already completed successfully."""
    pass


class CurrentlyRunningError(Exception):
    """Raised when another pipeline run is detected as in-progress (possible crash recovery)."""
    pass


class IdempotencyGuard:
    """
    Prevents double-execution of the EOD pipeline on the same trading date.

    Pattern:
        guard = IdempotencyGuard(session)
        if not guard.acquire(run_date):
            return  # Already done today
        try:
            # ... run pipeline ...
            guard.complete(run_date, stats)
        except Exception as e:
            guard.fail(run_date, str(e))
            raise
    """

    def __init__(self, session: Session):
        self.session = session

    def acquire(self, run_date: date) -> bool:
        """
        Attempts to acquire the run lock for today.

        Returns:
            True  — lock acquired, pipeline should proceed
            False — pipeline already completed today (COMPLETE status)

        Raises:
            CurrentlyRunningError — if status is RUNNING (may indicate a crash)
        """
        # Check existing entry
        existing = (
            self.session.query(PipelineRunLog)
            .filter(PipelineRunLog.run_date == run_date)
            .first()
        )

        if existing:
            if existing.status == "COMPLETE":
                logger.info(f"[IDEMPOTENCY] Pipeline already completed for {run_date}. Skipping.")
                return False
            elif existing.status == "RUNNING":
                raise CurrentlyRunningError(
                    f"Pipeline for {run_date} is already in RUNNING state. "
                    "If this is a crash recovery, manually update the row to FAILED and retry."
                )
            elif existing.status == "FAILED":
                # Previous run failed — allow retry
                logger.warning(f"[IDEMPOTENCY] Previous run for {run_date} FAILED. Retrying...")
                existing.status = "RUNNING"
                existing.started_at = datetime.now()
                existing.error_message = None
                existing.completed_at = None
                self.session.flush()
                return True

        # No existing entry — create new RUNNING row
        try:
            run_log = PipelineRunLog(
                run_date=run_date,
                status="RUNNING",
                started_at=datetime.now(),
            )
            self.session.add(run_log)
            self.session.flush()  # Flush to trigger UNIQUE constraint if duplicate
            logger.info(f"[IDEMPOTENCY] Lock acquired for {run_date}.")
            return True
        except IntegrityError:
            # Race condition: another process inserted concurrently
            self.session.rollback()
            logger.warning(f"[IDEMPOTENCY] Race condition detected for {run_date}. Skipping.")
            return False

    def complete(self, run_date: date, stats: dict) -> None:
        """Mark today's run as successfully completed."""
        run_log = (
            self.session.query(PipelineRunLog)
            .filter(PipelineRunLog.run_date == run_date)
            .first()
        )
        if run_log:
            run_log.status = "COMPLETE"
            run_log.completed_at = datetime.now()
            run_log.kill_switch_active = stats.get("kill_switch_active", False)
            run_log.candidates_screened = stats.get("candidates_screened", 0)
            run_log.candidates_passed = stats.get("candidates_passed", 0)
            run_log.new_setups_generated = stats.get("new_setups_generated", 0)
            run_log.positions_evaluated = stats.get("positions_evaluated", 0)
            self.session.flush()
            logger.info(f"[IDEMPOTENCY] Pipeline COMPLETE for {run_date}. Stats: {stats}")

    def fail(self, run_date: date, error: str) -> None:
        """Mark today's run as failed."""
        run_log = (
            self.session.query(PipelineRunLog)
            .filter(PipelineRunLog.run_date == run_date)
            .first()
        )
        if run_log:
            run_log.status = "FAILED"
            run_log.completed_at = datetime.now()
            run_log.error_message = error[:1000]  # Truncate to fit column
            self.session.flush()
            logger.error(f"[IDEMPOTENCY] Pipeline FAILED for {run_date}. Error: {error}")

    def get_last_run(self) -> dict | None:
        """Returns the most recent pipeline run record."""
        run_log = (
            self.session.query(PipelineRunLog)
            .order_by(PipelineRunLog.run_date.desc())
            .first()
        )
        if not run_log:
            return None
        return {
            "run_date": str(run_log.run_date),
            "status": run_log.status,
            "kill_switch_active": run_log.kill_switch_active,
            "new_setups_generated": run_log.new_setups_generated,
            "positions_evaluated": run_log.positions_evaluated,
            "started_at": str(run_log.started_at) if run_log.started_at else None,
            "completed_at": str(run_log.completed_at) if run_log.completed_at else None,
        }
