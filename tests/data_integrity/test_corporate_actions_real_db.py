"""Step 7 integration test on the REAL database: every verification row goes through the engine's real adjustment code path.

Runs only with STOCKBOT_DATA_TESTS=1 (fails loudly if the database is missing or the log is empty):
    set STOCKBOT_DATA_TESTS=1 && py -3 -m pytest tests/data_integrity -q        (STOCKBOT_DB=<path> to test a copy)
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

DB = Path(os.environ.get("STOCKBOT_DB") or Path(__file__).resolve().parents[2] / "finsight.db")
RUN = os.environ.get("STOCKBOT_DATA_TESTS") == "1"
if RUN and not DB.exists():
    raise RuntimeError(f"STOCKBOT_DATA_TESTS=1 but the database {DB} does not exist")
pytestmark = pytest.mark.skipif(not RUN, reason="needs STOCKBOT_DATA_TESTS=1 and the real database")

V = Path(__file__).resolve().parents[2] / "data/reference/verified_corporate_actions.csv"
ROWS = list(pd.read_csv(V).itertuples()) if V.exists() else []


@pytest.fixture(scope="module")
def session():
    from stockbot.data_checks.f2_engine_scan import session_for
    return session_for(str(DB))


def test_the_log_is_loaded():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    n = c.execute("select count(*) from corporate_actions_log").fetchone()[0]
    assert n > 20000, f"corporate_actions_log has only {n} rows: the Step 7 load has not run"


@pytest.mark.parametrize("r", ROWS, ids=[f"{r.symbol}-{r.ex_date}-{r.action_type}" for r in ROWS])
def test_verification_row_through_the_engine_path(session, r):
    from stockbot.data_checks.f2_verify_engine_path import verify_row
    v = pd.read_csv(V)
    same = v[(v.symbol == r.symbol) & (v.ex_date == r.ex_date) & v.action_type.isin(["SPLIT", "BONUS"])]
    expected = float(np.prod(same["expected_factor"])) if r.action_type in ("SPLIT", "BONUS") else 1.0
    res = verify_row(session, r, expected)
    assert res["result"] == "PASS", res
