"""The holiday-copy detector flags a date that repeats the previous session and nothing else."""
import sqlite3

from stockbot.data_checks.copy_detector import copy_dates


def _db(rows):
    c = sqlite3.connect(":memory:")
    c.execute("create table t(symbol text, trade_date text, close_raw real, volume_raw int)")
    c.executemany("insert into t values (?,?,?,?)", rows)
    return c


def test_flags_exact_copy_only():
    rows = []
    for s in ("A", "B", "C"):
        rows += [(s, "2024-01-24", 10.0, 100), (s, "2024-01-25", 11.0, 200),
                 (s, "2024-01-26", 11.0, 200),            # copy of 25th (holiday)
                 (s, "2024-01-29", 12.0, 300)]
    out = copy_dates(_db(rows), "t")
    assert list(out["trade_date"]) == ["2024-01-26"]


def test_real_sessions_with_same_close_but_new_volume_are_not_flagged():
    rows = []
    for s in ("A", "B"):
        rows += [(s, "2024-01-25", 11.0, 200), (s, "2024-01-26", 11.0, 250)]
    assert copy_dates(_db(rows), "t").empty
