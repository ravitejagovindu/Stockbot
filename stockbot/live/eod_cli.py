"""Command line for the EOD run: ``py scripts/run_eod.py [--date YYYY-MM-DD] [--mode PAPER|LIVE]``.

Runs ONE date through the runner (mode gate, freshness check, decide, state store, ticket files). It does not ingest data: run the ingestion step first.
Exit code 0 = processed (or already processed), 2 = refused (mode, freshness, surveillance data), 1 = any other error.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Optional, Sequence

from stockbot.config.shared import load_shared_config
from stockbot.live import MemoryViewNotValidated
from stockbot.live.runner import DataFreshnessError, ModeError, SurveillanceDataMissing, default_book, run_eod


def main(argv: Optional[Sequence[str]] = None, book=None) -> int:
    ap = argparse.ArgumentParser(description="Run the EOD decision step for one trading date (no ingestion, no orders).")
    ap.add_argument("--date", help="trading date YYYY-MM-DD (default: the latest weekday up to today)")
    ap.add_argument("--mode", choices=["PAPER", "LIVE"], help="override runtime.mode of the shared config (PAPER is the default there)")
    a = ap.parse_args(argv)
    try:
        r = run_eod(cfg=load_shared_config(), book=book or default_book(), as_of=date.fromisoformat(a.date) if a.date else None, mode=a.mode)
    except (ModeError, DataFreshnessError, SurveillanceDataMissing, MemoryViewNotValidated) as exc:
        print(f"REFUSED: {exc}")
        return 2
    print(f"{r.mode}: {r.as_of}: {len(r.decisions)} session(s) processed, tickets: {[str(p) for p in r.ticket_files]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
