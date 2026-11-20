"""Paper step of the daily job for momentum_calm (monthly): ONE EOD decision run for the latest weekday on sealed data. Thin wrapper: the engine path is stockbot.live.runner.run_eod
(PAPER mode, the shared config, the state database ``state/live_state.db``, one ticket file per session under ``state/tickets``). No order is sent anywhere and nothing is reported by hand:
a ticket made at the close of T is filled by the engine at the open of T+1 (shared fill rule, 0.10% slippage, shared costs) on the next run.

  py -3 scripts/paper_run.py [--date YYYY-MM-DD]

Refuses (exit 2) when the lake is not sealed through the date, when a lock is held, when STOCKBOT_RISK_PCT is set or STOCKBOT_VIEW=memory. STOCKBOT_NON_EQ defaults to ``held`` here.
Exit codes: 0 processed (or already processed), 2 refused, 4 a daily-update or run lock is held (try again later), 1 other error."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKBOT_NON_EQ", "held")

from stockbot.config.paths import lake_path  # noqa: E402
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.ingestion.daily_update import LAKE, seal_of  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.live import MemoryViewNotValidated  # noqa: E402
from stockbot.live.runner import Book, DataFreshnessError, ModeError, SurveillanceDataMissing, expected_session, run_eod  # noqa: E402
from stockbot.config.paths import state_db_path  # noqa: E402
from stockbot.live.state_store import StateStore  # noqa: E402
from stockbot.strategies.momentum_calm.paper import PAPER_START_CASH, paper_policy_extras, paper_strategy  # noqa: E402


def paper_book() -> Book:
    return Book.from_strategies([paper_strategy()], extra_policies=paper_policy_extras())


def locks_held() -> list:
    from stockbot.data.guard.runlock import lock_dir
    d = lock_dir()
    return sorted(p.name for p in d.glob("*.lock")) if d.exists() else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="momentum_calm paper step: one EOD decision run on sealed data (no orders).")
    ap.add_argument("--date", help="trading date YYYY-MM-DD (default: the latest weekday up to today)")
    a = ap.parse_args(argv)
    held = locks_held()
    if held:
        print(f"LOCKED: {held}: the data job or a run is active; nothing done")
        return 4
    as_of = date.fromisoformat(a.date) if a.date else expected_session(date.today())
    try:
        con = open_lake(lake_path())
        sealed = seal_of(con, LAKE)
        con.close()
        if sealed is None or sealed < as_of.isoformat():
            print(f"REFUSED: the lake is sealed through {sealed}, not {as_of}: the data step must finish first")
            return 2
        store = StateStore(state_db_path())
        try:
            if store.journal_count() == 0:
                store.initialise(PAPER_START_CASH)          # the account starts here, once; no deposit or withdrawal path exists in the state store
            r = run_eod(cfg=load_shared_config(), book=paper_book(), as_of=as_of, store=store, mode="PAPER")
        finally:
            store.close()
    except (ModeError, DataFreshnessError, SurveillanceDataMissing, MemoryViewNotValidated) as exc:
        print(f"REFUSED: {exc}")
        return 2
    print(f"{r.mode}: {r.as_of}: {len(r.decisions)} session(s) processed, tickets: {[str(p) for p in r.ticket_files]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
