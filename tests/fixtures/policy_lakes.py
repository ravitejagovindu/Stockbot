"""Fixture-lake variants for the exit-policy tests: FIXCO with a split/bonus on a chosen session (prices before it are unchanged in the lake, so the as-of view
adjusts them), with one session's bar missing, or with every bar after a date altered. Never touches finsight.db."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.fixtures import mini_lake
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()


def plain_lake(path: Path) -> Path:
    _make(path)
    return path


def lake_with_action(path: Path, ex_idx: int, kind: str = "SPLIT", num: int = 1, den: int = 5) -> Path:
    """A copy of the lake where FIXCO's raw prices from session ``ex_idx`` on are multiplied by the action's price factor (so the data is what an exchange file
    would show) and the matching corporate action row is inserted. SPLIT 1:5 -> factor 0.2; BONUS 1:1 -> 0.5."""
    _make(path)
    factor = num / den if kind == "SPLIT" else den / (den + num) if kind == "BONUS" else 1.0          # other types (RIGHTS ...) do not move the prices
    con = sqlite3.connect(path)
    con.execute("update market_data_lake set open_raw=open_raw*?, high_raw=high_raw*?, low_raw=low_raw*?, close_raw=close_raw*?, volume_raw=volume_raw/? "
                "where symbol='FIXCO' and trade_date>=?", (factor, factor, factor, factor, factor, DS[ex_idx].isoformat()))
    con.execute("insert into corporate_actions_log (symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('FIXCO', ?, ?, ?, ?, 'test', 'T1')",
                (DS[ex_idx].isoformat(), kind, num, den))
    con.commit(); con.close()
    return path


def lake_without_bar(path: Path, idx: int) -> Path:
    """FIXCO has no row on session ``idx`` (the index and the other symbols do)."""
    _make(path)
    con = sqlite3.connect(path)
    con.execute("delete from market_data_lake where symbol='FIXCO' and trade_date=?", (DS[idx].isoformat(),))
    con.commit(); con.close()
    return path


def lake_with_future_changed(path: Path, as_of) -> Path:
    """Every bar after ``as_of`` multiplied by 7, volume 1, plus a future split: decisions up to ``as_of`` must not change."""
    from datetime import timedelta
    _make(path)
    con = sqlite3.connect(path)
    con.execute("update market_data_lake set open_raw=open_raw*7, high_raw=high_raw*7, low_raw=low_raw*7, close_raw=close_raw*7, volume_raw=1 where trade_date>?", (as_of.isoformat(),))
    con.execute("insert into corporate_actions_log (symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('FIXCO', ?, 'SPLIT', 1, 2, 'x', 'T1')",
                ((as_of + timedelta(days=3)).isoformat(),))
    con.commit(); con.close()
    return path
