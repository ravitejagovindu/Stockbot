"""Daily health check of the live side (restructure Phase 10; replaces the old script that read the legacy ``pipeline_run_log``). Read-only. Exit code 1 if anything looks wrong.

Checks (each problem is one line):
  * the lake's latest session is not older than ``max_stale_days`` (the ingestion step has not run);
  * the state store is initialised, its schema is the supported one and ``rebuild()`` (a fold of the journal alone) equals the stored snapshot;
  * the state store has processed the lake's latest session (the EOD run has not run, or failed, for the newest data);
  * the newest session's Decisions carry no unreconciled assumed fills or exits older than ``unreconciled_days`` sessions (tickets nobody reported on).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Optional, Sequence

from stockbot.config.paths import lake_path, state_db_path
from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.live.state_store import StateStore, StateStoreError


def check(conn, store: StateStore, today: date, *, max_stale_days: int = 4, unreconciled_days: int = 3) -> list:
    problems = []
    ses = AsOfView(conn, today).sessions(lookback=unreconciled_days + 1)
    latest = ses[-1] if ses else None
    if latest is None or (today - latest).days > max_stale_days:
        problems.append(f"price data is stale (latest session: {latest})")
    try:
        snap = store.load()
    except StateStoreError as exc:
        return problems + [f"state store: {exc}"]
    if store.rebuild().to_json() != snap.to_json():
        problems.append("state store: the snapshot differs from the state rebuilt from the journal")
    if latest is not None and (snap.as_of is None or snap.as_of < latest):
        problems.append(f"state store is at {snap.as_of}, the lake is at {latest}: the EOD run has not processed the newest session")
    for s in ses[:-1] if len(ses) > 1 else []:
        d = store.decisions_for(s)
        if d is not None and any(f.code.startswith("UNRECONCILED") for f in d.flags) and (snap.pending or snap.positions):
            problems.append(f"{s}: assumed fills/exits are still unreconciled with the operator's reports")
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Daily health check of the live side (read-only; exit 1 if anything looks wrong).")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    a = ap.parse_args(argv)
    today = date.fromisoformat(a.today) if a.today else date.today()
    store = StateStore(state_db_path()) if state_db_path().exists() else None
    if store is None:
        print(f"PROBLEM: no state store at {state_db_path()} (the EOD runner has never run)")
        return 1
    problems = check(open_lake(lake_path()), store, today)
    for p in problems:
        print("PROBLEM:", p)
    print("health check: " + ("OK" if not problems else f"{len(problems)} problem(s)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
