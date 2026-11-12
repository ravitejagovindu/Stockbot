"""trend_breakout_100d (Stage 1): the strategy only PROPOSES. The breakout and SMA200 tests against an independent computation, the data rules (200 own bars, 198 of 200 present, a bar on
the as-of date), strictness of the comparison, today excluded from the 100-session maximum, the ADTV-then-symbol order as an explicit rank, the top-25 cut, the stop, the spec hash, no
look-ahead, and the path through the real engine (trailing_pct_15). Fixture lakes only (the series builder is the shared near_high_series_lake fixture, imported, not edited)."""
import ast
import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.engine.decide import EventData
from stockbot.engine.exit_policies.registry import policies_for
from stockbot.live.runner import Book, ModeError, strategies_for_mode
from stockbot.strategies.registry import StrategyRegistry, default_registry
from stockbot.strategies.spec import SpecError
from stockbot.strategies.trend_breakout_100d import SPEC, TrendBreakoutStrategy, register
from tests.fixtures import near_high_series_lake as L
from tests.fixtures.dummies import make_spec
from tests.fixtures.engine_run import run_days

ROOT = Path(__file__).resolve().parents[2]
P = SPEC.params
N = L.N                                                    # 330 sessions; the first session with 200 own bars is index 199


def view_of(path, ds, j):
    return AsOfView(open_lake(path), ds[j])


def propose(path, ds, j, symbols, strat=None):
    return (strat or TrendBreakoutStrategy()).propose(view_of(path, ds, j), list(symbols), ds[j], {}, {})


def flat_then(jump_at, level=100.0, jump_to=110.0):
    c = np.full(N, level)
    c[jump_at:] = jump_to
    return c


def independent(c, j):
    """(breakout, above_sma) from the adjusted series itself: prior 100 closes exclude today; SMA200 includes today."""
    return c[j] > c[j - 100:j].max(), c[j] > c[j - 199:j + 1].mean()


# ------------------------------------------------------------------------------------------------------------------------------------------------ the spec
def test_the_spec_carries_every_number_the_owner_fixed():
    assert (SPEC.id, SPEC.version, SPEC.status, SPEC.exit_policy) == ("trend_breakout_100d", "1.0.0", "research", "trailing_pct_15")
    assert SPEC.params == {"min_bars": 200, "min_present": 198, "breakout_lookback": 100, "sma_period": 200, "top_n": 25, "stop_fraction": 0.85, "adtv_sessions": 20}
    assert SPEC.universe_overrides == {} and SPEC.overlays == {} and SPEC.validation_ref is None


@pytest.mark.parametrize("key,value", [("min_bars", 201), ("min_present", 197), ("breakout_lookback", 99), ("sma_period", 199), ("top_n", 24), ("stop_fraction", 0.86), ("adtv_sessions", 21)])
def test_the_config_hash_changes_when_a_parameter_changes(key, value):
    assert replace(SPEC, params={**P, key: value}).config_hash() != SPEC.config_hash() and replace(SPEC).config_hash() == SPEC.config_hash()


def test_the_config_hash_also_covers_the_exit_policy():
    assert replace(SPEC, exit_policy="trailing_pct_14").config_hash() != SPEC.config_hash()


def test_status_research_cannot_run_in_live_or_paper_and_registration_is_explicit():
    b = Book.from_strategies([TrendBreakoutStrategy()])
    with pytest.raises(ModeError):
        strategies_for_mode(b, "LIVE")
    assert strategies_for_mode(b, "PAPER") == []
    with pytest.raises(SpecError):
        replace(SPEC, status="live")
    reg = StrategyRegistry()
    assert register(reg) is SPEC and reg.ids() == ["trend_breakout_100d"]
    with pytest.raises(SpecError):
        register(reg)
    assert len(default_registry) == 0


# ------------------------------------------------------------------------------------------------------------------------------------- breakout and trend
def test_signal_matches_an_independent_computation_on_noisy_series(tmp_path):
    rng = np.random.default_rng(11)
    series = {f"S{k}": L.rise(100 + k, 0.0004 * (k - 3)) * (1 + 0.01 * rng.standard_normal(N)) for k in range(8)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    seen = 0
    for j in (199, 230, 260, 290, 329):
        got = {x.symbol for x in propose(p, ds, j, series)[0]}
        want = {s for s, c in series.items() if all(independent(c, j))}
        assert got == want, (j, got ^ want)
        seen += len(want)
    assert seen > 0


def test_breakout_is_strict_today_is_excluded_from_the_maximum_and_the_sma_must_also_be_cleared(tmp_path):
    series = {"BRK": flat_then(300),                                      # 110 on 300: above the prior 100 closes (100) and the SMA200
              "EQ": flat_then(300, 100.0, 100.0),                         # equals the prior maximum: not a breakout
              "BELOW": np.concatenate([np.full(150, 300.0), np.full(N - 150, 100.0)]),     # high 300s early: SMA200 is ~149 on 300
              "LOW": flat_then(300, 100.0, 99.99)}
    series["BELOW"][300:] = 110.0                                         # breaks the prior 100 closes (100) but stays under its SMA200
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    assert [x.symbol for x in propose(p, ds, 300, series)[0]] == ["BRK"]
    assert independent(series["BELOW"], 300) == (True, False) and independent(series["EQ"], 300) == (False, False)
    assert propose(p, ds, 299, series)[0] == []                          # before the jump nothing breaks out
    series2 = {"BRK": flat_then(300)}
    series2["BRK"][301] = 109.0
    p2 = tmp_path / "lake2.db"
    ds2 = L.build(p2, series2)
    assert propose(p2, ds2, 301, series2)[0] == []                       # 109 is below the 110 of yesterday, which is now inside the prior 100
    series2["BRK"][301] = 111.0
    p3 = tmp_path / "lake3.db"
    ds3 = L.build(p3, series2)
    assert [x.symbol for x in propose(p3, ds3, 301, series2)[0]] == ["BRK"]


def test_the_maximum_uses_exactly_the_prior_100_closes(tmp_path):
    c = np.full(N, 100.0)
    c[199:299] = 100.0
    c[200] = 120.0                                                       # a spike 100 sessions before 300: outside the prior 100 closes of 300 (indices 200..299 include it!)
    c[300] = 110.0
    series = {"SPIKE_IN": c.copy()}
    c2 = c.copy()
    c2[200] = 100.0
    c2[199] = 120.0                                                      # one session older: outside the prior 100 (indices 200..299), so 110 breaks out
    series["SPIKE_OUT"] = c2
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    assert max(series["SPIKE_IN"][200:300]) == 120.0 and max(series["SPIKE_OUT"][200:300]) == 100.0
    assert [x.symbol for x in propose(p, ds, 300, series)[0]] == ["SPIKE_OUT"]


# ------------------------------------------------------------------------------------------------------------------------------------- data rules
def test_a_name_needs_200_bars_and_a_bar_on_the_as_of_date(tmp_path):
    base = L.rise(100, 0.001)
    series = {"OK": base, "SHORT": base, "GONE": base}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, skip={"SHORT": set(range(0, 151)), "GONE": {260}})   # SHORT's first bar is index 151: fewer than 200 bars up to the end of the lake
    assert {x.symbol for x in propose(p, ds, 259, series)[0]} == {"OK", "SHORT", "GONE"} - {"SHORT"}
    assert {x.symbol for x in propose(p, ds, 260, series)[0]} == {"OK"}          # no bar on the as-of session: not proposed
    assert {x.symbol for x in propose(p, ds, 329, series)[0]} == {"OK", "GONE"}


def test_gap_guard_two_missing_of_200_pass_three_drop(tmp_path):
    base = L.rise(100, 0.001)
    series = {"GAP2": base, "GAP3": base, "NONE": base, "OLD3": base}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, skip={"GAP2": {290, 291}, "GAP3": {290, 291, 292}, "OLD3": {80, 81, 82}})
    assert {x.symbol for x in propose(p, ds, 300, series)[0]} == {"GAP2", "NONE", "OLD3"}      # OLD3's gap is before the 200-session window (index 101..300)
    assert "GAP3" in {x.symbol for x in propose(p, ds, 289, series)[0]}
    assert "GAP3" not in {x.symbol for x in propose(p, ds, 300, series)[0]}


def test_a_split_inside_the_window_does_not_fake_or_hide_a_breakout(tmp_path):
    rng = np.random.default_rng(5)
    series = {"SPL": L.rise(150, 0.002) * (1 + 0.002 * rng.standard_normal(N))}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"SPL": (280, 1, 5)})
    for j in (270, 290, 329):
        got = {x.symbol for x in propose(p, ds, j, series)[0]}
        assert (got == {"SPL"}) == all(independent(series["SPL"], j)), j
    raw_after = 0.2 * series["SPL"][290]
    assert raw_after < series["SPL"][270:280].max()                       # a raw-price version would see a ~80% fall


# ------------------------------------------------------------------------------------------------------------------------------------- rank, cut, stop
def test_order_is_adtv_descending_then_symbol_as_an_explicit_ordinal_rank_and_top_25_cut(tmp_path):
    series = {f"V{k:02d}": L.rise(100, 0.001) for k in range(30)}
    vol = {f"V{k:02d}": 6_000_000 + 100_000 * k for k in range(30)}
    vol.update({"V00": 6_000_000, "V01": 6_000_000})                      # a tie at the bottom: symbol breaks it (not in the top 25 here)
    p = tmp_path / "lake.db"
    ds = L.build(p, series, volume=vol)
    props, state = propose(p, ds, 300, series)
    syms = [x.symbol for x in props]
    assert len(props) == 25 and syms[:3] == ["V29", "V28", "V27"] and state == {}
    assert [x.rank for x in props] == [float(25 - i) for i in range(25)]
    assert sorted(props, key=lambda x: (-x.rank, x.symbol)) == props
    two = {"TIEA": L.rise(100, 0.001), "TIEC": L.rise(100, 0.001), "TIEB": L.rise(100, 0.001)}
    p2 = tmp_path / "lake2.db"
    ds2 = L.build(p2, two, volume={"TIEB": 12_000_000})
    assert [x.symbol for x in propose(p2, ds2, 300, two)[0]] == ["TIEB", "TIEA", "TIEC"]        # bigger ADTV first, then symbol
    s3 = TrendBreakoutStrategy(replace(SPEC, params={**P, "top_n": 3}))
    assert [x.symbol for x in propose(p, ds, 300, series, s3)[0]] == ["V29", "V28", "V27"]


def test_rank_ignores_how_far_above_the_breakout_a_close_is(tmp_path):
    big = flat_then(300, 100.0, 150.0)
    small = flat_then(300, 100.0, 100.5)
    series = {"BIG": big, "SMALL": small}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, volume={"BIG": 6_000_000, "SMALL": 7_000_000})
    assert [x.symbol for x in propose(p, ds, 300, series)[0]] == ["SMALL", "BIG"]


def test_the_stop_is_0_85_times_the_signal_day_adjusted_close_in_the_as_of_basis(tmp_path):
    rng = np.random.default_rng(3)
    series = {"SPL": L.rise(150, 0.0022) * (1 + 0.002 * rng.standard_normal(N))}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"SPL": (280, 1, 5)})
    done = 0
    for j, basis in ((270, 1.0), (290, 0.2)):
        got = propose(p, ds, j, series)[0]
        if not got:
            continue
        (x,) = got
        close_asof = float(series["SPL"][j]) * basis
        assert x.reference_price == pytest.approx(close_asof, rel=1e-12) and x.stop == pytest.approx(0.85 * close_asof, rel=1e-12)
        assert x.signal_date == ds[j] and x.strategy_id == "trend_breakout_100d" and x.target is None
        done += 1
    assert done >= 1


# ------------------------------------------------------------------------------------------------------------------------------------- no look-ahead, determinism
def test_changing_every_row_after_the_as_of_date_does_not_change_the_proposals(tmp_path):
    series = {"A": L.rise(100, 0.002), "B": L.rise(120, 0.0015), "C": L.rise(100, 0.001)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, volume={"C": 9_000_000})
    alt = tmp_path / "alt.db"
    shutil.copy(p, alt)
    eng = create_engine(f"sqlite:///{alt.as_posix()}")
    with eng.begin() as c:
        c.execute(text("update market_data_lake set open_raw=open_raw*7, high_raw=high_raw*7, low_raw=low_raw*0.1, close_raw=close_raw*0.2, volume_raw=volume_raw*3 where trade_date>:d"),
                  {"d": ds[290].isoformat()})
        c.execute(text("insert into corporate_actions_log(symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('A', :d, 'SPLIT', 1, 50, 'test', 'T1')"),
                  {"d": ds[291].isoformat()})
    eng.dispose()
    for j in (230, 260, 290):
        a, sa = propose(p, ds, j, series)
        b, sb = propose(alt, ds, j, series)
        assert a == b and sa == sb and a
    assert propose(p, ds, 260, series) == propose(p, ds, 260, series)           # deterministic


def test_a_second_registered_strategy_does_not_change_these_proposals(tmp_path):
    series = {"A": L.rise(100, 0.002), "B": L.rise(120, 0.0015)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    alone = propose(p, ds, 260, series)
    reg = StrategyRegistry()
    register(reg)
    reg.register(make_spec("dummy_two"))
    assert propose(p, ds, 260, series) == alone and json.dumps(alone[1]) == "{}"


def test_the_strategy_package_imports_only_what_a_strategy_may_import():
    pkg = ROOT / "stockbot" / "strategies" / "trend_breakout_100d"
    allowed_std = {"__future__", "math", "typing", "dataclasses", "datetime", "collections"}
    for f in sorted(pkg.rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [n.module] if isinstance(n, ast.ImportFrom) and n.module else [a.name for a in n.names] if isinstance(n, ast.Import) else []
            for m in mods:
                top = m.split(".")[0]
                if top == "stockbot":
                    assert m.startswith(("stockbot.strategies.base", "stockbot.strategies.spec", "stockbot.strategies.trend_breakout_100d")), (f.name, m)
                else:
                    assert top in allowed_std, (f.name, m)


# ------------------------------------------------------------------------------------------------------------------------------------- through the engine
SECTORS = {"T_TRAIL": "S1", "T_RUN": "S2"}


@pytest.fixture(scope="module")
def engine_lake(tmp_path_factory):
    trail = L.rise(100, 0.002)
    trail[261:] = trail[260] * 0.80                                       # on session 261 the close drops 20% below the highest close (260): the trailing stop (15%) fires
    series = {"T_TRAIL": trail, "T_RUN": L.rise(100, 0.0015)}
    p = tmp_path_factory.mktemp("tb_engine") / "lake.db"
    ds = L.build(p, series)
    return p, ds


def run(engine_lake, days=range(199, 290)):
    p, ds = engine_lake
    s = TrendBreakoutStrategy()
    return run_days(p, [ds[i] for i in days], [s], policies_for([s.spec]), events=EventData(sectors=SECTORS))


def test_through_the_engine_the_trailing_stop_exits_and_the_policy_is_the_library_one(engine_lake):
    p, ds = engine_lake
    decs, st = run(engine_lake)
    first = [t for d in decs for t in d.new_tickets if d.as_of == ds[199]]
    assert {t.symbol for t in first} == {"T_TRAIL", "T_RUN"} and all(t.stop == pytest.approx(0.85 * t.reference_price) for t in first)
    closed = {c.symbol: c for d in decs for c in d.closed}
    t = closed["T_TRAIL"]
    assert t.entry_date == ds[200] and t.exit_reason == "STOP_HIT" and t.exit_date == ds[261]
    assert "T_RUN" not in closed                                          # the steady riser never falls 15% below its highest close, so it is still open


def test_determinism_through_the_engine_on_the_fixture_lake(engine_lake):
    (a, sa), (b, sb) = run(engine_lake), run(engine_lake)
    assert [d.to_json() for d in a] == [d.to_json() for d in b] and sa.to_json() == sb.to_json() and any(d.fills for d in a) and any(d.closed for d in a)
