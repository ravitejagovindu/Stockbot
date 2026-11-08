"""Entry-bar rule on the REAL lake (STOCKBOT_DATA_TESTS=1, read-only): every legacy trade in the six pooled CSVs is rebuilt from its entry price, stop and shares and
stepped through its real entry bar with the engine's generic stepping; the outcome (stopped on the entry day or not, and the exit price) must equal what the legacy
simulator recorded. Disagreements that come from DATA (the legacy run saw a lower low than the lake holds today: its own recorded lowest_low is at or below the
stop) are counted separately; disagreements caused by the RULE must be 0 (decision C1)."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
RUN = os.environ.get("STOCKBOT_DATA_TESTS") == "1"
pytestmark = pytest.mark.skipif(not RUN, reason="needs STOCKBOT_DATA_TESTS=1 and the real database")


def test_entry_bar_rule_agrees_with_every_legacy_trade_on_the_real_lake():
    from stockbot.config.shared import load_shared_config
    from stockbot.data.asof import AsOfView
    from stockbot.data.lake import open_lake
    from stockbot.engine.decide import bar_of
    from stockbot.engine.stepping import step_position
    from stockbot.engine.types import Position
    from stockbot.risk.costs import CostModel
    from tests.fixtures.dummies import FixedPolicy

    cfg = load_shared_config()
    costs = CostModel.from_shared(cfg.costs)
    conn = open_lake()
    t = pd.concat([pd.read_csv(p) for p in sorted((ROOT / "backtest" / "outputs_recomputed_net").glob("trades_CFG-0?_pooled.csv"))], ignore_index=True)
    u = t.drop_duplicates(subset=["symbol", "entry_date", "stop", "shares"]).reset_index(drop=True)
    pol = FixedPolicy()
    checked = both = neither = rule_diff = data_diff = nobar = 0
    for r in u.itertuples(index=False):
        day = pd.Timestamp(r.entry_date).date()
        view = AsOfView(conn, day)
        bar = bar_of(view, r.symbol)
        if bar is None:
            nobar += 1
            continue
        checked += 1
        pos = Position("x", "s", r.symbol, None, day, r.entry_price, r.stop, r.stop, None, float(r.shares), int(r.shares), r.shares * (r.entry_price - r.stop), "fixed",
                       highest_high=r.entry_price, last_close=r.entry_price)
        out = step_position(pos, bar, day, view, pol, costs, cfg.execution.exit_slippage_pct)
        new_stopped = out.closed and bool(out.exits) and out.exits[0].reason == "STOP_HIT"
        legacy_stopped = str(r.exit_date) == str(r.entry_date) and r.exit_reason == "STOP_HIT"
        if new_stopped and legacy_stopped:
            both += 1
            assert out.exits[0].price == pytest.approx(r.exit_price, abs=1e-6)
        elif not new_stopped and not legacy_stopped:
            neither += 1
        elif legacy_stopped and r.lowest_low <= r.stop and bar.low > r.stop:
            data_diff += 1                                  # the legacy run's own recorded low was through the stop; today's lake holds a low ABOVE the stop (data, not rule)
            assert r.exit_price == pytest.approx(r.stop * (1 - cfg.execution.exit_slippage_pct / 100.0), rel=1e-4)      # the rule applied to the legacy low gives the legacy price
        else:
            rule_diff += 1
    print(f"entry-bar real-lake check: {checked} legacy trades checked, {nobar} without a bar today; stopped on both={both}, stopped on neither={neither}, "
          f"data differences={data_diff}, RULE differences={rule_diff}")
    assert checked > 1500 and rule_diff == 0
