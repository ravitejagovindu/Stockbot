"""The class of every table in the database (db-guard design R2, R5): which tables are sealed by date, which are insert-only, which are exempt and why.

A table that is not listed here and is not a ``_guard_*`` / ``sqlite_*`` object is an UNREGISTERED table: ``install`` refuses it and the R5 test fails.
Adding a table = adding one ``Rule`` here (one reviewed change) and calling ``guard.ensure``; ``docs/shared/db-guard/GUARD.md`` explains how.

``volatile`` columns are left out of the "is this the same row?" comparison of an insert-only table and of the per-day checksum of a sealed table: surrogate ids and load timestamps
change on a legitimate reload, the facts do not (design decision D9).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DATED = "DATED_APPEND_ONLY"
INSERT_ONLY = "INSERT_ONLY"
EXEMPT = "EXEMPT"
CLASSES = (DATED, INSERT_ONLY, EXEMPT)
GUARD_PREFIX = "_guard_"


@dataclass(frozen=True)
class Rule:
    table: str
    cls: str
    date_col: Optional[str] = None          # DATED only: ISO-text date column the seal compares against
    key: tuple = ()                         # the columns that identify a row (a conflicting insert has the same key)
    volatile: tuple = ()                    # columns that may differ on a legitimate re-insert / reload
    reason: str = ""                        # EXEMPT only: why


def _d(table, date_col, key, volatile=()):
    return Rule(table, DATED, date_col, tuple(key), tuple(volatile))


def _i(table, key, volatile=()):
    return Rule(table, INSERT_ONLY, None, tuple(key), tuple(volatile))


def _e(table, reason):
    return Rule(table, EXEMPT, reason=reason)


RULES: dict = {r.table: r for r in (
    # DATED_APPEND_ONLY: history read by results; a day is loaded, then sealed
    _d("market_data_lake", "trade_date", ("symbol", "trade_date"), ("id", "created_at", "loaded_at")),
    _d("shares_outstanding", "effective_date", ("symbol", "effective_date"), ("id", "created_at")),
    _d("asm_gsm_daily_snapshot", "snapshot_date", ("snapshot_date", "framework", "symbol"), ("fetched_at",)),
    _d("asm_gsm_snapshot_raw", "snapshot_date", ("snapshot_date", "endpoint"), ("fetched_at",)),
    _d("index_gap_fill", "trade_date", ("symbol", "trade_date")),
    _d("market_data_non_eq", "trade_date", ("symbol", "trade_date", "series"), ("id", "created_at")),      # BE/BZ/BL rows (non-eq-series): a held position is marked on them; never read by eligibility or entries
    _d("shares_outstanding_pit", "effective_date", ("symbol", "effective_date"), ("id", "derived_at")),      # not in the file yet: created by scripts/provenance/f2b_build_pit_shares.py when it is run for real
    # INSERT_ONLY: facts that can arrive late, reference tables, archives, ledgers
    _i("corporate_actions_log", ("symbol", "ex_date", "action_type"), ("id", "created_at", "loaded_at")),
    _i("earnings_board_meeting", ("query_symbol", "row_hash"), ("id",)),
    _i("earnings_results_filing", ("query_symbol", "row_hash"), ("id",)),
    _i("earnings_api_raw", ("endpoint", "query_symbol"), ("fetched_at",)),
    _i("earnings_symbol_map", ("lake_symbol", "query_symbol")),
    _i("isin_symbol_map", ("isin", "symbol", "first_date"), ("applied_at",)),
    _i("securities_master", ("symbol",), ("created_at", "updated_at")),
    _i("market_data_lake_yahoo_archive", ("symbol", "trade_date"), ("id", "created_at", "archived_at")),
    _i("account_ledger", ("id",), ("created_at",)),
    _i("trade_analytics_log", ("id",), ("closed_at",)),
    # EXEMPT (each with its reason)
    _e("market_data_lake_staging", "staging: raw bhavcopy is deleted and re-inserted per date by design (F2 provenance input)"),
    _e("bhavcopy_fetch_log", "fetch log: rewritten on retry, read by no result"),
    _e("asm_gsm_snapshot_log", "fetch log: one row per fetch attempt, read by no result"),
    _e("earnings_collect_log", "fetch log: one row per fetch attempt, read by no result"),
    _e("regime_state", "legacy kill-switch state, derived from the lake and upserted per date"),
    _e("pipeline_run_log", "live-system working table (RUNNING to COMPLETE per day)"),
    _e("active_positions", "live-system working table (positions are updated daily)"),
    _e("daily_watchlist", "live-system working table (execution status is updated)"),
    _e("asm_gsm_list", "legacy refresher table, empty, no reader"),
    _e("earnings_calendar", "legacy, empty, no reader"),
)}

# tables that are registered for the day a script creates them (they are not in the real file today)
NOT_IN_THE_REAL_FILE = ("shares_outstanding_pit",)

# the tables a backtest-type run reads (AsOfView / MemoryAsOfView / the engine / the earnings events); their guard state goes into every run manifest (R4)
BACKTEST_READS = ("market_data_lake", "corporate_actions_log", "earnings_symbol_map", "earnings_api_raw", "earnings_board_meeting")

NON_EQ_READS = ("market_data_non_eq",)      # added to the run record when STOCKBOT_NON_EQ=held (the run then reads this table)


def backtest_reads() -> tuple:
    """BACKTEST_READS, plus the non-EQ table when the switch STOCKBOT_NON_EQ=held is on (with the switch off no run reads it, so manifests are unchanged)."""
    from stockbot.data.non_eq import switch_on
    return BACKTEST_READS + NON_EQ_READS if switch_on() else BACKTEST_READS


def is_guard_object(name: str) -> bool:
    return name.startswith(GUARD_PREFIX) or name.startswith("sqlite_")


def rule_for(table: str) -> Optional[Rule]:
    return RULES.get(table)
