"""
FInsight Trading Engine — APScheduler for 5 PM IST Daily Pipeline
"""
from __future__ import annotations

import logging
from datetime import date

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
_scheduler: BackgroundScheduler | None = None


def run_eod_pipeline():
    """Entry point called by APScheduler. Includes Catch-Up Logic for missed days."""
    today = date.today()
    logger.info(f"[SCHEDULER] Trigger fired. Evaluating runs up to {today}...")

    try:
        from data.db.connection import get_session
        from data.db.models import PipelineRunLog
        from live_runner.pipeline import EODPipeline
        import yfinance as yf
        import pandas as pd
        from datetime import timedelta

        with get_session() as session:
            # 1. Find last successful run date anchored to actual equity data in market_data_lake
            from sqlalchemy import text
            latest_equity_date = session.execute(
                text("SELECT MAX(trade_date) FROM market_data_lake WHERE symbol NOT IN ('NIFTY50_INDEX', 'INDIA_VIX')")
            ).scalar()

            if latest_equity_date:
                if isinstance(latest_equity_date, str):
                    from datetime import datetime
                    latest_equity_date = datetime.strptime(latest_equity_date, "%Y-%m-%d").date()
                last_date = latest_equity_date
            else:
                last_run = (
                    session.query(PipelineRunLog.run_date)
                    .filter(PipelineRunLog.status == "COMPLETE")
                    .order_by(PipelineRunLog.run_date.desc())
                    .first()
                )
                last_date = last_run[0] if last_run else (today - timedelta(days=1))

            if last_date >= today:
                logger.info("[SCHEDULER] System is fully caught up.")
                return

            # Clear any stale pipeline logs after last_date so IdempotencyGuard allows re-processing
            session.execute(
                text("DELETE FROM pipeline_run_log WHERE run_date > :last_date"),
                {"last_date": last_date}
            )
            session.commit()

            # 2. Get true trading days using Yahoo Finance Nifty50 index
            logger.info(f"[SCHEDULER] Fetching actual trading calendar between {last_date} and {today}...")
            start_fetch = last_date + timedelta(days=1)
            end_fetch = today + timedelta(days=1)
            
            df = yf.download("^NSEI", start=start_fetch, end=end_fetch, progress=False)
            
            if df.empty:
                logger.info("[SCHEDULER] No trading days found in this window (weekends/holidays). Skipping.")
                return
                
            df.reset_index(inplace=True)
            date_col = next((c for c in df.columns if "date" in str(c).lower()), None)
            trading_days = pd.to_datetime(df[date_col], utc=True).dt.date.tolist()

            logger.info(f"[SCHEDULER] Found {len(trading_days)} trading day(s) to process: {trading_days}")

            # 3. Sequentially run the pipeline for each missing day
            for t_date in trading_days:
                logger.info(f"[SCHEDULER] --- Executing Catch-Up run for {t_date} ---")
                pipeline = EODPipeline(session=session)
                pipeline.run(eval_date=t_date)
                session.commit()  # Commit each day successfully before moving to the next

            logger.info("[SCHEDULER] All catch-up and current runs completed successfully.")

    except Exception as e:
        logger.error(f"[SCHEDULER] EOD pipeline FAILED: {e}", exc_info=True)
        _send_failure_alert(today, str(e))


def _send_failure_alert(run_date: date, error: str):
    """Send desktop notification on pipeline failure."""
    try:
        from winotify import Notification, audio
        toast = Notification(
            app_id="FInsight Trading Engine",
            title="⚠️ EOD Pipeline Failed",
            msg=f"{run_date}: {error[:100]}",
            duration="long",
        )
        toast.set_audio(audio.Default, loop=False)
        toast.show()
    except Exception:
        pass  # Notification failure must never crash the main process


def start_scheduler():
    """Initialize and start the APScheduler."""
    global _scheduler

    from config import load_config
    config = load_config()
    eod_source = config.get("data", {}).get("eod_source", "kite")
    trigger_hour = 19 if eod_source == "bhavcopy" else 17

    _scheduler = BackgroundScheduler(timezone=IST)
    _scheduler.add_job(
        run_eod_pipeline,
        trigger=CronTrigger(hour=trigger_hour, minute=0, timezone=IST),
        id="eod_pipeline",
        name="FInsight EOD Pipeline",
        replace_existing=True,
        misfire_grace_time=300,  # 5-minute grace period if scheduler was down at trigger time
    )
    _scheduler.start()
    logger.info(f"[SCHEDULER] APScheduler started. Next fire time: {trigger_hour}:00 IST daily (Source: {eod_source}).")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=True)
        logger.info("[SCHEDULER] APScheduler stopped.")
