"""The 19:30 IST daily job: the data step, then (only if it succeeded) the momentum_calm paper step. Replaces the task that runs scripts/daily_data_update.py alone (docs/shared/daily-update/SCHEDULER.md).

  py -3 scripts/daily_job.py [--scheduled]        (--scheduled is passed to the data step)

Step 1 scripts/daily_data_update.py (exit 0 = done or nothing to do). Any other exit code ends the job with THAT code and the paper step does not run (3 = today's file not published yet, the scheduler
retries in 20 minutes; 4 = locked; 5 = stale lock, read the message). Step 2 scripts/paper_run.py reads sealed data only; its exit code is the job's (2 = refused, for example a weekday holiday)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    rc = subprocess.call([sys.executable, str(HERE / "daily_data_update.py"), *args])
    if rc != 0:
        print(f"daily_job: data step exit {rc}; the paper step is not run")
        return rc
    rc = subprocess.call([sys.executable, str(HERE / "paper_run.py")])
    print(f"daily_job: paper step exit {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
