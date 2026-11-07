"""Permanent calendar integrity tests on the REAL database (F2).

Slow (minutes: one pass over millions of rows), so they only run when STOCKBOT_DATA_TESTS=1 and the database has the
relevant table; otherwise skipped (a clean clone has no database).  Run before and after any swap:

    set STOCKBOT_DATA_TESTS=1 && py -3 -m pytest tests/data_integrity -q   (STOCKBOT_DB=<path> to test another copy)
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from scripts.f2_copy_detector import copy_dates, special_sessions

DB = Path(os.environ.get("STOCKBOT_DB") or Path(__file__).resolve().parents[2] / "finsight.db")
RUN = os.environ.get("STOCKBOT_DATA_TESTS") == "1"
if RUN and not DB.exists():                       # asked for the data tests but there is nothing to test: fail loudly, never skip
    raise RuntimeError(f"STOCKBOT_DATA_TESTS=1 but the database {DB} does not exist")
pytestmark = pytest.mark.skipif(not RUN, reason="needs STOCKBOT_DATA_TESTS=1 and the real database")


def _con():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    c.execute("PRAGMA query_only=ON")
    return c


def _has(c, table):
    return c.execute("select 1 from sqlite_master where name=?", (table,)).fetchone() is not None


@pytest.mark.parametrize("table", ["market_data_lake_staging", "market_data_lake"])
def test_no_date_copies_the_previous_session(table):
    c = _con()
    if not _has(c, table):
        pytest.skip(f"no table {table}")
    flagged = copy_dates(c, table)
    assert flagged.empty, f"{table}: dates identical to the previous session: {list(flagged['trade_date'])}"


def test_staging_dates_are_nifty_dates_or_documented_special_sessions():
    c = _con()
    if not _has(c, "market_data_lake_staging"):
        pytest.skip("no staging table")
    nifty = {r[0] for r in c.execute("select trade_date from market_data_lake where symbol='NIFTY50_INDEX'")}
    stg = {r[0] for r in c.execute("select distinct trade_date from market_data_lake_staging")}
    start = min(nifty)
    unexplained = sorted(d for d in stg if d >= start and d not in nifty and d not in special_sessions())
    assert not unexplained, f"staging dates with neither a Nifty row nor a special_sessions entry: {unexplained}"
    missing = sorted(d for d in nifty if d <= max(stg) and d not in stg)
    assert not missing, f"Nifty dates without Bhavcopy rows: {missing}"
