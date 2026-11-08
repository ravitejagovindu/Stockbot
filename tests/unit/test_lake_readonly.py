"""stockbot.data.lake: the lake is opened read-only (a write attempt must fail) - runs on a fixture lake file, never finsight.db."""
import sqlite3

import pytest

from stockbot.data.lake import open_lake
from tests.fixtures.lakefile import lake_path  # noqa: F401  (fixture)


def test_lake_is_read_only(lake_path):
    before = lake_path.read_bytes()
    con = open_lake(lake_path)
    for stmt in ("insert into market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw) values ('X','2030-01-01',1,1,1,1,1)",
                 "delete from market_data_lake", "create table t(x)", "update market_data_lake set close_raw=0"):
        with pytest.raises(sqlite3.OperationalError):
            con.execute(stmt)
            con.commit()
    con.close()
    assert lake_path.read_bytes() == before


def test_open_lake_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        open_lake(tmp_path / "nope.db")
