"""
FInsight Trading Engine - scheduler for the daily EOD run (restructure Phase 9).

The job is thin: it calls ``stockbot.live.runner.run_eod`` for the expected session. It does NOT ingest data (ingestion is its own step, run before this
one by whatever schedules it) and it does not look at Yahoo or any other network source: sessions come from the lake. A failed freshness check, a mode refusal or
any other error is logged and raised as a desktop alert; the run is idempotent per trading date, so the next firing simply tries again.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
_scheduler: BackgroundScheduler | None = None


def run_eod_job(book=None, today: Optional[date] = None):
    """Entry point called by APScheduler (and by hand). Returns the RunResult, or None if the run could not happen."""
    from stockbot.config.shared import load_shared_config
    from stockbot.live.runner import default_book, run_eod

    today = today or date.today()
    try:
        cfg = load_shared_config()
        result = run_eod(cfg=cfg, book=book or default_book(), today=today)
        logger.info("[SCHEDULER] %s run for %s: %d session(s) processed, %d ticket file(s)", result.mode, result.as_of, len(result.decisions), len(result.ticket_files))
        return result
    except Exception as e:                                           # noqa: BLE001 - the scheduler thread must survive
        logger.error("[SCHEDULER] EOD run FAILED: %s", e, exc_info=True)
        _send_failure_alert(today, str(e))
        return None


def _send_failure_alert(run_date: date, error: str):
    """Send desktop notification on failure."""
    try:
        from winotify import Notification, audio
        toast = Notification(app_id="FInsight Trading Engine", title="EOD run failed", msg=f"{run_date}: {error[:100]}", duration="long")
        toast.set_audio(audio.Default, loop=False)
        toast.show()
    except Exception:
        pass  # Notification failure must never crash the main process


def start_scheduler():
    """Initialize and start the APScheduler."""
    global _scheduler
    from stockbot.config.shared import load_shared_config

    cfg = load_shared_config()
    eod_source = cfg.data.eod_source
    trigger_hour = 19 if eod_source == "bhavcopy" else 17

    _scheduler = BackgroundScheduler(timezone=IST)
    _scheduler.add_job(
        run_eod_job,
        trigger=CronTrigger(hour=trigger_hour, minute=0, timezone=IST),
        id="eod_run",
        name="FInsight EOD run",
        replace_existing=True,
        misfire_grace_time=300,
    )
    _scheduler.start()
    logger.info(f"[SCHEDULER] APScheduler started. Next fire time: {trigger_hour}:00 IST daily (Source: {eod_source}).")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=True)
        logger.info("[SCHEDULER] APScheduler stopped.")
