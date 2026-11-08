"""Helpers to drive ``stockbot.engine.decide`` day by day on the fixture lake (never touches finsight.db)."""
from __future__ import annotations

from stockbot.config.shared import load_shared_config
from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.engine.decide import EventData, decide
from stockbot.engine.types import State
from tests.fixtures import mini_lake

CFG = load_shared_config()
EVENTS = EventData(sectors={"FIXCO": "IT"})


def sessions():
    return mini_lake.sessions()


def run_days(lake_path, days, strategies, policies, *, state=None, overlays=None, strict=True, mode="backtest", events=EVENTS, cash=1_000_000.0):
    """decide() once per session in ``days``; returns (list of Decisions, final State)."""
    conn = open_lake(lake_path)
    st = state if state is not None else State.initial(cash)
    out = []
    for d in days:
        dec, st = decide(d, st, AsOfView(conn, d), strategies, CFG, events, policies=policies, overlays=overlays, strict=strict, mode=mode)
        out.append(dec)
    return out, st


def policies(*ps):
    return {p.id: p for p in ps}
