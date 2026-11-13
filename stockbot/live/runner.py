"""The EOD runner (restructure Phase 9): thin. It does NOT ingest data and it never talks to a broker.

Order of work for one trading date T:
  1. the mode gate: PAPER is the default; LIVE runs only strategies with status "live" (which need a validation_ref) and refuses to run without one;
  2. the freshness check: the lake must already hold session T (ingestion is its own step, run before this one; this module only LOOKS at the lake, read-only);
  3. surveillance data: ASM/GSM names from the daily snapshot table; in LIVE a missing snapshot for T stops the run (fail-closed), in PAPER it is noted in the result;
  4. LiveAdapter.process(T): applies the operator's reports, one decide per unseen session, journals everything in the separate state database
     (idempotent per trading date: a date already in the journal changes nothing);
  5. ticket output: one JSON file per processed session with the new tickets, what was blocked and why, and the flags (including unreconciled items).
Tickets are suggestions for the operator to act on by hand; there is no order-routing code path anywhere in this package (tests/unit/test_regulatory_barrier.py).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from stockbot.config.paths import lake_path, state_db_path, tickets_dir
from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.data.sector_map import SectorLookup  # noqa: F401  (the shared lookup; re-exported here for the live package and the research wrappers)
from stockbot.engine.decide import EventData
from stockbot.engine.exit_policies.registry import policies_for
from stockbot.engine.types import Decisions, to_plain
from stockbot.live.adapter import LiveAdapter
from stockbot.live.state_store import StateStore

MODES = ("PAPER", "LIVE")


class ModeError(RuntimeError):
    """The requested mode cannot run (for example LIVE without a validated strategy)."""


class DataFreshnessError(RuntimeError):
    """The lake does not hold the session yet: run the ingestion step first."""


class SurveillanceDataMissing(RuntimeError):
    """LIVE only: there is no ASM/GSM snapshot for the date (fail-closed)."""


@dataclass(frozen=True)
class Book:
    """The strategies (objects with a spec), exit policies and overlays the runner may use. The default book is EMPTY: no strategy exists in the tree."""
    strategies: tuple = ()
    policies: Mapping[str, Any] = field(default_factory=dict)
    overlays: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_strategies(cls, strategies, overlays: Optional[Mapping[str, Any]] = None, extra_policies=None) -> "Book":
        """A book whose policies are built from the strategies' specs (library ids; strategy-owned policies through ``extra_policies``)."""
        return cls(strategies=tuple(strategies), policies=policies_for([s.spec for s in strategies], extra=extra_policies), overlays=dict(overlays or {}))


def default_book() -> Book:
    return Book()


def strategies_for_mode(book: Book, mode: str) -> list:
    mode = str(mode).upper()
    if mode not in MODES:
        raise ModeError(f"mode must be one of {MODES}")
    if mode == "LIVE":
        chosen = [s for s in book.strategies if s.spec.status == "live"]
        if not chosen:
            raise ModeError("LIVE needs at least one strategy with status 'live'; none is registered, so nothing runs")
        for s in chosen:
            if not s.spec.validation_ref:
                raise ModeError(f"strategy {s.spec.id} is 'live' without a validation_ref")
        return chosen
    return [s for s in book.strategies if s.spec.status in ("paper", "live")]        # research strategies never run in the live package


def expected_session(today: date) -> date:
    """The latest weekday on or before today (a weekday holiday shows up as a freshness failure, which is harmless: nothing is processed)."""
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def check_freshness(conn, as_of: date) -> date:
    """Return the lake's latest session on or before as_of; raise DataFreshnessError unless it IS as_of."""
    ses = AsOfView(conn, as_of).sessions(lookback=1)
    latest = ses[-1] if ses else None
    if latest != as_of:
        raise DataFreshnessError(f"the lake's latest session is {latest}, not {as_of}: run the ingestion step first")
    return latest


def load_asm_ranges(conn, as_of: date) -> Optional[dict]:
    """{SYMBOL: [(as_of, as_of)]} from the ASM/GSM daily snapshot of as_of; None if the table or the day is missing."""
    if conn.execute("select 1 from sqlite_master where type='table' and name='asm_gsm_daily_snapshot'").fetchone() is None:
        return None
    if conn.execute("select 1 from asm_gsm_daily_snapshot where snapshot_date=? limit 1", (as_of.isoformat(),)).fetchone() is None:
        return None
    rows = conn.execute("select symbol from asm_gsm_daily_snapshot where snapshot_date=?", (as_of.isoformat(),)).fetchall()
    return {r[0].upper(): [(as_of, as_of)] for r in rows}


def write_tickets(dec: Decisions, directory: Path) -> Path:
    """One file per session, written atomically; the same Decisions always give the same bytes."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    body = {"as_of": dec.as_of.isoformat(), "tickets": to_plain(dec.new_tickets), "blocked": to_plain(dec.blocked), "flags": to_plain(dec.flags),
            "fills_assumed": to_plain(dec.fills), "exits_assumed": to_plain(dec.exits), "note": "Suggestions for the operator. Nothing is sent to any broker."}
    path = directory / f"tickets_{dec.as_of.isoformat()}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


@dataclass(frozen=True)
class RunResult:
    mode: str
    as_of: date
    decisions: tuple
    ticket_files: tuple
    asm_data: bool


def run_eod(*, cfg, book: Book, as_of: Optional[date] = None, store: Optional[StateStore] = None, lake: Optional[Path] = None, out_dir: Optional[Path] = None,
            reports: Sequence = (), mode: Optional[str] = None, today: Optional[date] = None) -> RunResult:
    mode = str(mode or cfg.runtime.mode).upper()
    strategies = strategies_for_mode(book, mode)
    as_of = as_of or expected_session(today or date.today())
    conn = open_lake(lake or lake_path())
    check_freshness(conn, as_of)
    asm = load_asm_ranges(conn, as_of)
    if asm is None and mode == "LIVE":
        raise SurveillanceDataMissing(f"no ASM/GSM snapshot for {as_of}: LIVE fails closed")
    own_store = store is None
    store = store or StateStore(state_db_path())
    try:
        if store.journal_count() == 0:
            store.initialise(cfg.runtime.paper_start_equity)
        adapter = LiveAdapter(store, conn, strategies, book.policies, cfg, EventData(sectors=SectorLookup(), asm_ranges=asm or {}), overlays=book.overlays)
        new = adapter.process(as_of, reports)
        files = tuple(write_tickets(d, out_dir or tickets_dir()) for d in new)
    finally:
        if own_store:
            store.close()
    return RunResult(mode, as_of, tuple(new), files, asm is not None)
