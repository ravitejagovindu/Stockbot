"""scripts/daily_health_check.py — Exit code 1 if anything looks wrong. Run after the nightly job."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from sqlalchemy import text

# Add project root to sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.db.connection import get_session


def main() -> int:
    problems = []
    with get_session() as s:
        run = s.execute(
            text("SELECT run_date, status FROM pipeline_run_log ORDER BY run_date DESC LIMIT 1")
        ).first()
        last_bar = s.execute(text("SELECT MAX(trade_date) FROM market_data_lake")).scalar()

        if run is None or run[1] != "COMPLETE":
            problems.append(f"last pipeline run not COMPLETE: {run}")
        if run and last_bar and str(run[0]) != str(last_bar):
            problems.append(f"pipeline date {run[0]} != latest data {last_bar}")
        if last_bar and (date.today() - date.fromisoformat(str(last_bar))).days > 4:
            problems.append(f"price data is stale (latest bar: {last_bar})")

        max_dw_run = s.execute(text("SELECT MAX(run_date) FROM daily_watchlist")).scalar()
        if max_dw_run:
            n_pend = s.execute(
                text(
                    "SELECT COUNT(*) FROM daily_watchlist WHERE execution_status='PENDING' "
                    "AND run_date < :max_run"
                ),
                {"max_run": max_dw_run},
            ).scalar()
            if n_pend:
                problems.append(f"{n_pend} old tickets still PENDING (paper trader not running?)")

        max_pipe_run = s.execute(text("SELECT MAX(run_date) FROM pipeline_run_log")).scalar()
        if max_pipe_run:
            stale = s.execute(
                text(
                    "SELECT COUNT(*) FROM active_positions WHERE mode='PAPER' AND "
                    "(last_evaluated_date IS NULL OR last_evaluated_date < :max_run)"
                ),
                {"max_run": max_pipe_run},
            ).scalar()
            if stale:
                problems.append(f"{stale} paper positions not advanced on the last run")

    if problems:
        print("\n".join(f"[ERROR] {p}" for p in problems), file=sys.stderr)
        return 1

    print("OK: Daily health check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
