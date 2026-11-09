"""validation.random_baseline / paired_stats: matched random draws reuse the engine's fill and exit code, are seeded and eligibility-bound; the paired statistics are seeded."""
import sqlite3

import numpy as np
import pandas as pd
import pytest

from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.validation import paired_stats
from stockbot.validation.random_baseline import draw_matched_random
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy
from tests.fixtures.engine_run import CFG
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()
POL = FixedPolicy(id="timed", max_days=5)
COLS = "open_raw, high_raw, low_raw, close_raw"


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("lake") / "lake.db"
    _make(p, with_split=False)
    con = sqlite3.connect(p)
    for sym, k, first in (("AAA", 1.05, 0), ("BBB", 0.9, 0), ("CCC", 1.2, 0), ("YOUNG", 1.0, 200)):
        con.execute(f"insert into market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange) "
                    f"select ?, trade_date, open_raw*?, high_raw*?, low_raw*?, close_raw*?, volume_raw, exchange from market_data_lake where symbol='FIXCO' and trade_date>=?",
                    (sym, k, k, k, k, DS[first].isoformat()))
    con.commit(); con.close()
    return p


def actual_trades():
    rows = []
    for i, ix in enumerate((260, 270, 280)):
        px = 100.0 + 0.25 * ix + 0.5
        rows.append({"unique_trade_id": f"W_{i}", "symbol": "FIXCO", "entry_date": DS[ix], "entry_price": px, "stop": px * 0.92, "window": "W"})
    return pd.DataFrame(rows)


def draw(lake, seed=3, **kw):
    conn = open_lake(lake)
    return draw_matched_random(actual_trades(), sessions=DS[200:330], view_at=lambda d: AsOfView(conn, d), shared_config=CFG, policy=POL, equity=1_000_000.0,
                               draws_per_trade=2, seed=seed, **kw)


def test_same_seed_same_draws_and_other_seeds_differ(lake):
    a, b = draw(lake, 3), draw(lake, 3)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 6
    assert len({tuple(draw(lake, s)["symbol"]) for s in range(1, 8)}) > 1


def test_draws_use_the_engine_exit_policy_and_the_matched_relative_stop(lake):
    d = draw(lake)
    assert set(d["exit_reason"]) == {"TIME_EXIT"} and set(d["days_held"]) == {5}                    # the supplied policy's rule, executed by the engine stepping
    conn = open_lake(lake)
    for r in d.itertuples():
        i = DS.index(r.entry_date)
        ref = AsOfView(conn, DS[i - 1]).adjusted_bars(r.symbol, lookback=1)["close_adj"].iloc[-1]
        assert r.stop == pytest.approx(ref * 0.92)                                                  # (entry - stop) / entry of the actual trade, on the draw's signal close
        assert r.entry_price == pytest.approx(AsOfView(conn, r.entry_date).adjusted_bars(r.symbol, lookback=1)["open_adj"].iloc[-1] * 1.001)   # next open x entry slippage
        assert r.net_r < r.gross_r                                                                  # costs were charged


def test_the_pool_is_the_shared_universe_minus_the_actual_symbol(lake):
    for seed in range(1, 11):
        d = draw(lake, seed)
        assert set(d["symbol"]) <= {"AAA", "BBB", "CCC"} and "FIXCO" not in set(d["symbol"]) and "YOUNG" not in set(d["symbol"])      # YOUNG: under 252 sessions
    only = draw(lake, pool_filter=lambda view, s: s == "AAA")
    assert set(only["symbol"]) == {"AAA"} and len(only) == 3                                          # one eligible name left: one draw per actual trade


def test_forward_returns_are_measured_from_the_fill_price(lake):
    d = draw(lake).iloc[0]
    conn = open_lake(lake)
    closes = AsOfView(conn, DS[329]).raw_bars(d["symbol"], lookback=None, start=d["entry_date"])["close_raw"]
    after = [c for dt, c in closes.items() if dt > d["entry_date"]]
    assert d["ret_1"] == pytest.approx((after[0] / d["entry_price"] - 1) * 100) and d["ret_20"] == pytest.approx((after[19] / d["entry_price"] - 1) * 100)


def test_unfilled_draws_are_counted_not_hidden(lake):
    conn = open_lake(lake)
    a = actual_trades().iloc[:1].copy()
    a["entry_date"] = DS[329]                                                                       # no session after it: nothing can be simulated
    d = draw_matched_random(a, sessions=DS[200:330], view_at=lambda x: AsOfView(conn, x), shared_config=CFG, policy=POL, equity=1e6, draws_per_trade=2, seed=1)
    assert d.empty and sum(d.attrs["unfilled"].values()) == 2


# ------------------------------------------------------------------ paired statistics
def stats_frames(shift=1.0):
    rng = np.random.default_rng(0)
    n = 40
    actual = pd.DataFrame({"unique_trade_id": [f"t{i}" for i in range(n)], "window": ["A"] * 20 + ["B"] * 20, "entry_date": [DS[i // 2] for i in range(n)],
                           "gross_r": rng.normal(0.3, 1, n), "net_r": rng.normal(0.2, 1, n), "days_held": rng.integers(3, 30, n)})
    rand_rows = []
    for i in range(n):
        for k in range(3):
            rand_rows.append({"matched_trade_id": f"t{i}", "window": actual.window[i], "gross_r": rng.normal(0.0, 1), "net_r": rng.normal(-0.1, 1), "days_held": int(rng.integers(3, 30))})
    rand = pd.DataFrame(rand_rows)
    for h in paired_stats.HORIZONS:
        base = rng.normal(0, 3, n)
        actual[f"ret_{h}"] = base + shift
        for c, v in zip(("ret",), (None,)):
            pass
        rand[f"ret_{h}"] = np.repeat(base, 3) + rng.normal(0, 0.5, 3 * n)
    return actual, rand


def test_paired_statistics_are_reproducible_for_a_seed_and_move_with_it():
    a, r = stats_frames()
    x, y = paired_stats.paired_statistics(a, r, seed=5), paired_stats.paired_statistics(a, r, seed=5)
    assert x == y
    z = paired_stats.paired_statistics(a, r, seed=6)
    assert x["windows"]["Pooled"]["horizons"][0]["perm_p"] != z["windows"]["Pooled"]["horizons"][0]["perm_p"] or x["windows"]["Pooled"]["horizons"][0]["clustered_t"] != z["windows"]["Pooled"]["horizons"][0]["clustered_t"]
    assert x["paired_trades"] == 40 and set(x["windows"]) == {"A", "B", "Pooled"} and x["windows"]["A"]["n_trades"] == 20 and x["windows"]["Pooled"]["n_trades"] == 40


def test_paired_difference_and_significance_follow_the_data():
    a, r = stats_frames(shift=1.0)
    res = paired_stats.paired_statistics(a, r, seed=1)["windows"]["Pooled"]
    hz = res["horizons"][0]
    merged_diff = (a["ret_1"].values - r.groupby("matched_trade_id")["ret_1"].mean().reindex(a["unique_trade_id"]).values).mean()
    assert hz["paired_diff"] == pytest.approx(merged_diff) and hz["paired_diff"] == pytest.approx(1.0, abs=0.4)
    assert hz["status"] == "Significant" and hz["perm_p"] < paired_stats.BONFERRONI_ALPHA and hz["trade_t"] > 3
    null_a, null_r = stats_frames(shift=0.0)
    assert paired_stats.paired_statistics(null_a, null_r, seed=1)["windows"]["Pooled"]["horizons"][0]["status"] == "Not Sig"
    e = res["expectancy"]
    assert e["actual"]["net"] == pytest.approx(a["net_r"].mean()) and e["random_raw_draws"]["n"] == len(r)
    assert e["paired_diff_net"]["mean"] == pytest.approx((a["net_r"].values - r.groupby("matched_trade_id")["net_r"].mean().reindex(a["unique_trade_id"]).values).mean())


def test_trimmed_mean_and_report():
    assert paired_stats.trimmed_mean([1, 2, 3, 4, 100], 0.2) == pytest.approx(3.0)
    assert np.isnan(paired_stats.trimmed_mean([np.nan]))
    assert paired_stats.trimmed_mean([1.0, 3.0]) == 2.0
    a, r = stats_frames()
    text = paired_stats.format_report(paired_stats.paired_statistics(a, r, seed=1))
    assert "Pooled" in text and "T+1" in text and "seed 1" in text
