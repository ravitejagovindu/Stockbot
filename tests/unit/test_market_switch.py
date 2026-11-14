"""market_switch_v1 (docs/shared/market-switch/BRIEF.md): the rule on synthetic series, the engine wiring on a fixture lake, SQL = memory view, one code path for live, overlays=[] changes nothing, and
the replay of the OLD provenance kill switch (scripts/provenance/regime/regime_filter.py) against the overlay: the daily ACTIVE/CLEAR state must match on every session. Fixture lakes only,
except the replay on the real series (STOCKBOT_DATA_TESTS=1)."""
import dataclasses
import hashlib
import importlib.util
import inspect
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockbot.config.shared import load_shared_config
from stockbot.data.asof import AsOfView, NIFTY, VIX
from stockbot.data.lake import open_lake
from stockbot.engine.decide import EngineInputError, decide
from stockbot.engine.types import State, to_plain
from stockbot.overlays import describe_default_overlays, resolve_default_overlays
from stockbot.overlays.market_switch import ACTIVE, CLEAR, MarketSwitch, MarketSwitchDataError, MarketSwitchParams
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.engine_run import CFG, EVENTS, policies, run_days
from tests.fixtures.lakefile import _make

ROOT = Path(__file__).resolve().parents[2]
DS = mini_lake.sessions()
SIG, ENTRY, CRASH = DS[mini_lake.BREAKOUT], DS[mini_lake.ENTRY], DS[mini_lake.CRASH]
STOP = 159.115349


# ---------------------------------------------------------------------------------------------------------------- a fake as-of view over explicit series
class FakeView:
    """index_bars like AsOfView: the last ``lookback`` closes up to the as-of session; a missing row is absent, a null close raises TypeError (float(None)) as the real view does."""

    def __init__(self, dates, nifty, vix, i):
        self.dates, self.nifty, self.vix, self.i = dates, nifty, vix, i
        self.as_of = dates[i]

    def index_bars(self, symbol, lookback=None):
        ser = self.nifty if symbol == NIFTY else self.vix
        rows = [(self.dates[j], ser[j]) for j in range(self.i + 1) if ser[j] != "missing"]
        rows = rows[-lookback:] if lookback else rows
        if any(v is None for _, v in rows):
            raise TypeError("float() argument must be a string or a real number, not 'NoneType'")
        return pd.DataFrame({"close_raw": [v for _, v in rows]}, index=[d for d, _ in rows])


def run_series(nifty, vix, params=None):
    ms = MarketSwitch(params)
    dates = [date(2020, 1, 1) + timedelta(days=k) for k in range(len(nifty))]
    st, out = {}, []
    for i in range(len(nifty)):
        sig, st = ms.evaluate(FakeView(dates, nifty, vix, i), st)
        out.append(sig)
    return out


def states(sigs):
    return [s["state"] for s in sigs]


# ---------------------------------------------------------------------------------------------------------------- the rule
def test_vix_trigger_is_strict_and_names_its_reason():
    n = [100.0] * 250
    assert states(run_series(n, [22.0] * 250))[-1] == CLEAR                      # 22.0 is not above 22.0
    s = run_series(n, [22.0] * 249 + [22.01])
    assert s[-1]["state"] == ACTIVE and s[-1]["reason"] == "VIX_ABOVE_22" and s[-1]["block_entries"] is True


def test_nifty_trigger_is_strict_and_needs_the_full_sma200_window():
    flat = [100.0] * 250
    assert states(run_series(flat, [15.0] * 250))[-1] == CLEAR                   # close == SMA200 does not trigger
    s = run_series(flat[:-1] + [90.0], [15.0] * 250)
    assert s[-1]["state"] == ACTIVE and s[-1]["reason"] == "NIFTY_BELOW_SMA200"
    assert s[-1]["nifty_sma_trigger"] == pytest.approx((199 * 100.0 + 90.0) / 200)
    both = run_series(flat[:-1] + [90.0], [15.0] * 249 + [30.0])
    assert both[-1]["reason"] == "NIFTY_BELOW_SMA200+VIX_ABOVE_22"


def test_warm_up_a_missing_sma200_cannot_trigger_and_a_missing_sma20_fails_the_reentry():
    falling = [200.0 - k for k in range(150)]                                    # 150 closes: no SMA200, close far below the 150-day mean
    assert set(states(run_series(falling, [15.0] * 150))) == {CLEAR}
    assert states(run_series(falling, [15.0] * 149 + [30.0]))[-1] == ACTIVE      # VIX still triggers during warm-up
    n = [100.0] * 5 + [101.0] * 14                                               # 19 closes: no SMA20 yet
    v = [30.0] + [15.0] * 18
    s = run_series(n, v)
    assert all(x["state"] == ACTIVE and x["reentry_count"] == 0 and x["nifty_sma_reentry"] is None for x in s[1:])


def hysteresis_series():
    """250 flat sessions, a VIX spike, then recovery with 19.0 and a miss at exactly 20.0 (strict: 20.0 is NOT below 20.0)."""
    v = [15.0] * 250 + [30.0] + [19.0, 19.0, 20.0, 19.0, 19.0, 19.0, 19.0]
    n = [100.0 + 0.01 * k for k in range(len(v))]                                # rising: above both SMAs
    return n, v


def test_hysteresis_counts_consecutive_qualifying_sessions_resets_on_any_miss_and_releases_on_the_third():
    n, v = hysteresis_series()
    s = run_series(n, v)[250:]
    assert [(x["state"], x["reentry_count"], x["reason"]) for x in s] == [
        (ACTIVE, 0, "VIX_ABOVE_22"),
        (ACTIVE, 1, "REENTRY_COUNT 1/3"), (ACTIVE, 2, "REENTRY_COUNT 2/3"),
        (ACTIVE, 0, "REENTRY_COUNT 0/3"),                                          # VIX 20.0: miss, reset
        (ACTIVE, 1, "REENTRY_COUNT 1/3"), (ACTIVE, 2, "REENTRY_COUNT 2/3"),
        (CLEAR, 3, "REENTRY_COUNT 3/3"),                                           # the third qualifying session itself releases
        (CLEAR, 3, None)]


def test_while_active_the_trigger_conditions_are_irrelevant_only_the_reentry_condition_counts():
    v = [15.0] * 250 + [30.0] + [21.0] * 5 + [19.0] * 3                          # VIX 21: below the trigger but above the re-entry level: stays ACTIVE, count 0
    n = [100.0 + 0.01 * k for k in range(len(v))]
    s = run_series(n, v)[250:]
    assert [x["state"] for x in s] == [ACTIVE] * 8 + [CLEAR] and [x["reentry_count"] for x in s][:6] == [0] * 6


def test_reentry_needs_nifty_above_its_sma20_strictly():
    v = [15.0] * 250 + [30.0] + [15.0] * 49                                      # flat Nifty: close == SMA20, not above it
    n = [100.0] * len(v)
    s = run_series(n, v)[250:]
    assert all(x["state"] == ACTIVE and x["reentry_count"] == 0 for x in s)


def test_a_missing_or_null_vix_or_nifty_close_raises():
    n = [100.0] * 250
    for bad in ("missing", None):
        v = [15.0] * 249 + [bad]
        with pytest.raises((MarketSwitchDataError, TypeError)):
            run_series(n, v)
    with pytest.raises(MarketSwitchDataError, match="no VIX close"):
        run_series(n, [15.0] * 249 + ["missing"])
    with pytest.raises(MarketSwitchDataError, match="no Nifty close"):
        run_series(n[:-1] + ["missing"], [15.0] * 250)


def test_the_switch_is_pure_and_deterministic():
    n, v = hysteresis_series()
    assert run_series(n, v) == run_series(n, v)


# ---------------------------------------------------------------------------------------------------------------- the replay of the OLD code
def _old_module():
    p = ROOT / "scripts" / "provenance" / "regime" / "regime_filter.py"
    spec = importlib.util.spec_from_file_location("old_regime_filter", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["old_regime_filter"] = m
    spec.loader.exec_module(m)
    return m


OLD_CFG = {"macro": {"nifty_kill_sma_period": 200, "vix_kill_threshold": 22.0, "nifty_reentry_sma_period": 20, "vix_reentry_threshold": 20.0, "reentry_consecutive_sessions": 3},
           "data": {"nifty_symbol": NIFTY, "vix_symbol": VIX}}


def old_states(dates, nifty, vix):
    """The old RegimeFilter (persist=False, in-memory state), fed the same series; only its data fetch is replaced (it read market_data_lake)."""
    ns, vs = pd.Series(nifty, index=dates, dtype=float), pd.Series(vix, index=dates, dtype=float)

    class Old(_old_module().RegimeFilter):
        def _fetch_closes(self, symbol, as_of, lookback):
            s = ns if symbol == NIFTY else vs
            return s[s.index <= as_of].iloc[-lookback:]

    f = Old(OLD_CFG, session=None, persist=False)
    return [ACTIVE if f.evaluate(d).kill_switch_active else CLEAR for d in dates]


def test_the_old_code_and_the_overlay_agree_on_every_session_of_random_series():
    for seed in range(8):
        rng = np.random.default_rng(seed)
        n_s = 900
        nifty = 10000 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, n_s) + 0.02 * np.sin(np.arange(n_s) / (40 + 10 * seed))))
        vix = np.round(np.clip(18 + 6 * np.sin(np.arange(n_s) / (25 + 7 * seed)) + rng.normal(0, 2.0, n_s), 9, 45), 2)
        dates = [date(2016, 1, 1) + timedelta(days=k) for k in range(n_s)]
        new = states(run_series(list(nifty), list(vix)))
        old = old_states(dates, nifty, vix)
        assert new == old, (seed, [i for i, (a, b) in enumerate(zip(new, old)) if a != b][:5])
        assert ACTIVE in new and CLEAR in new                                    # the series do exercise both states


def test_the_old_code_and_the_overlay_agree_on_the_hand_series():
    for n, v in (hysteresis_series(),):
        dates = [date(2020, 1, 1) + timedelta(days=k) for k in range(len(n))]
        assert states(run_series(n, v)) == old_states(dates, n, v)


@pytest.mark.skipif(os.environ.get("STOCKBOT_DATA_TESTS") != "1", reason="real-lake replay: STOCKBOT_DATA_TESTS=1")
def test_the_old_code_and_the_overlay_agree_on_every_session_of_the_real_series_2016_to_2026(monkeypatch):
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)
    db = os.environ.get("STOCKBOT_DB") or str(ROOT / "finsight.db")
    conn = open_lake(db)
    nifty = dict(conn.execute("select trade_date, close_raw from market_data_lake where symbol=? order by trade_date", (NIFTY,)).fetchall())
    vix = dict(conn.execute("select trade_date, close_raw from market_data_lake where symbol=? order by trade_date", (VIX,)).fetchall())
    all_days = [date.fromisoformat(str(k)[:10]) for k in nifty]
    ns = pd.Series([nifty[k] for k in nifty], index=all_days)
    vs = pd.Series([vix[k] for k in nifty], index=all_days)                      # zero Nifty sessions lack a VIX close in the window (counted before this was built)
    old = dict(zip(all_days, old_states(all_days, ns.values, vs.values)))
    ms, st, n_active, mismatches = MarketSwitch(), {}, 0, []
    for d in all_days:                                                           # the overlay reads through the REAL as-of view
        sig, st = ms.evaluate(AsOfView(conn, d), st)
        n_active += sig["state"] == ACTIVE
        if sig["state"] != old[d]:
            mismatches.append(d)
    assert not mismatches, mismatches[:10]
    assert n_active > 0 and len(all_days) > 2000


# ---------------------------------------------------------------------------------------------------------------- the engine on a fixture lake
@pytest.fixture(scope="module")
def base_lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("ms") / "lake.db"
    _make(p)
    return p


def lake_with_vix(tmp_path, vix_by_index):
    """A copy of the fixture lake with the given VIX closes (session index -> value)."""
    p = tmp_path / "vix.db"
    _make(p)
    con = sqlite3.connect(p)
    for i, val in vix_by_index.items():
        con.execute("update market_data_lake set close_raw=? where symbol='INDIA_VIX' and trade_date=?", (val, DS[i].isoformat()))
    con.commit()
    con.close()
    return p


def strat():
    return ScriptedStrategy(make_spec("dummy"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": STOP}]})


def days(a, b):
    return [d for d in DS if a <= d <= b]


def test_entries_are_blocked_while_active_with_reason_market_switch_and_the_state_is_logged(tmp_path):
    p = lake_with_vix(tmp_path, {mini_lake.BREAKOUT: 30.0})                      # VIX spike on the signal session
    decs, st = run_days(p, days(DS[298], DS[304]), [strat()], policies(FixedPolicy()))
    by = {d.as_of: d for d in decs}
    assert by[SIG].new_tickets == () and not st.positions
    assert [(b.reason, b.stage, b.symbol) for b in by[SIG].blocked] == [("MARKET_SWITCH", "overlay", "FIXCO")]
    assert by[SIG].overlay_state_after["market_switch_v1"]["state"] == ACTIVE and by[SIG].overlay_state_after["market_switch_v1"]["reason"] == "VIX_ABOVE_22"
    assert by[DS[298]].overlay_state_after["market_switch_v1"]["state"] == CLEAR


def test_a_clear_switch_changes_nothing_a_ticket_is_made(base_lake):
    decs, st = run_days(base_lake, days(DS[298], DS[304]), [strat()], policies(FixedPolicy()))
    by = {d.as_of: d for d in decs}
    assert len(by[SIG].new_tickets) == 1 and not by[SIG].blocked
    assert all(d.overlay_state_after["market_switch_v1"]["state"] == CLEAR for d in decs)


def test_exits_and_open_positions_are_unaffected_by_the_switch(tmp_path):
    p = lake_with_vix(tmp_path, {i: 35.0 for i in range(mini_lake.ENTRY, mini_lake.N_SESSIONS)})   # ACTIVE from the entry session on; the ticket was made while CLEAR
    decs, st = run_days(p, days(DS[298], DS[306]), [strat()], policies(FixedPolicy()))
    by = {d.as_of: d for d in decs}
    assert by[ENTRY].fills and by[ENTRY].overlay_state_after["market_switch_v1"]["state"] == ACTIVE      # yesterday's ticket still fills at the open
    assert by[CRASH].closed and by[CRASH].exits                                                          # the gap through the stop is still exited
    assert not by[ENTRY].blocked and not by[CRASH].blocked


def test_a_missing_vix_close_stops_the_session_in_every_mode(tmp_path):
    p = tmp_path / "novix.db"
    _make(p)
    con = sqlite3.connect(p)
    con.execute("delete from market_data_lake where symbol='INDIA_VIX' and trade_date=?", (DS[299].isoformat(),))
    con.commit()
    con.close()
    for strict, mode in ((True, "backtest"), (False, "live"), (False, "paper")):
        with pytest.raises(MarketSwitchDataError):
            run_days(p, days(DS[298], DS[300]), [strat()], policies(FixedPolicy()), strict=strict, mode=mode)


def test_the_engine_result_is_identical_under_the_sql_and_the_memory_view(tmp_path, monkeypatch):
    p = lake_with_vix(tmp_path, {mini_lake.BREAKOUT: 30.0, mini_lake.BREAKOUT + 1: 19.0})
    digests = {}
    for view in ("sql", "memory"):
        monkeypatch.setenv("STOCKBOT_VIEW", view)
        decs, st = run_days(p, days(DS[250], DS[310]), [strat()], policies(FixedPolicy()))
        digests[view] = hashlib.sha256(json.dumps([to_plain(d) for d in decs] + [to_plain(st)], sort_keys=True, default=str).encode()).hexdigest()
    assert digests["sql"] == digests["memory"]


def test_sql_and_memory_views_give_the_same_switch_states_on_every_session(tmp_path, monkeypatch):
    p = lake_with_vix(tmp_path, {250: 30.0, 251: 19.0, 252: 19.0, 253: 21.0, 254: 19.0, 255: 19.0, 256: 19.0, 257: 19.0})
    out = {}
    for view in ("sql", "memory"):
        monkeypatch.setenv("STOCKBOT_VIEW", view)
        conn = open_lake(p)
        ms, st, seq = MarketSwitch(), {}, []
        for d in DS[200:300]:
            sig, st = ms.evaluate(AsOfView(conn, d), st)
            seq.append((sig["state"], sig["reason"], sig["reentry_count"], sig["vix_close"], sig["nifty_sma_trigger"], sig["nifty_sma_reentry"]))
        out[view] = seq
    assert out["sql"] == out["memory"] and ACTIVE in [s[0] for s in out["sql"]] and CLEAR in [s[0] for s in out["sql"]]


# ---------------------------------------------------------------------------------------------------------------- live uses the same code path; overlays=[] moves nothing
def test_live_adapter_and_backtest_share_the_one_decide_call_and_the_default_comes_from_the_shared_config():
    from stockbot.backtest import runner
    from stockbot.live import adapter
    for mod in (runner, adapter):
        src = inspect.getsource(mod)
        assert "decide(" in src and "default_overlays" in src and "market_switch" not in src.lower() and "MarketSwitch" not in src      # neither adapter knows the rule: only decide() does
    assert list(CFG.overlays.default) == ["market_switch_v1"]
    assert set(resolve_default_overlays(CFG)) == {"market_switch_v1"} and resolve_default_overlays(CFG, []) == {}
    assert "resolve_default_overlays" in inspect.getsource(decide)


def test_the_live_adapter_blocks_entries_when_the_switch_is_active_and_none_when_switched_off(tmp_path):
    from stockbot.live.adapter import LiveAdapter
    assert inspect.signature(LiveAdapter.__init__).parameters["default_overlays"].default is None        # None = the shared default
    p = lake_with_vix(tmp_path, {mini_lake.BREAKOUT: 30.0})
    conn = open_lake(p)
    st = State.initial(1_000_000.0)
    s = strat()
    for d in days(DS[298], SIG):
        dec, st = decide(d, st, AsOfView(conn, d), [s], CFG, EVENTS, policies=policies(FixedPolicy()), strict=False, mode="live", default_overlays=None)   # exactly what the adapter passes
    assert [b.reason for b in dec.blocked] == ["MARKET_SWITCH"] and dec.new_tickets == ()


def test_unknown_default_overlay_is_refused():
    with pytest.raises(ValueError, match="unknown default overlay"):
        resolve_default_overlays(CFG, ["nope"])


def digest(default_overlays):
    """The same deterministic fixture run as the digest taken on master b27431d (before this branch): decisions, final state, trades, equity, daily, blocked."""
    import tempfile
    from stockbot.backtest.runner import run_backtest
    tmp = Path(tempfile.mkdtemp())
    p = tmp / "lake.db"
    _make(p)
    s1 = ScriptedStrategy(make_spec("dummy"), {DS[300].isoformat(): [{"symbol": "FIXCO", "stop": 159.115349}], DS[310].isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
    conn = open_lake(p)
    st, decs = State.initial(1_000_000.0), []
    for d in days(DS[295], DS[329]):
        dec, st = decide(d, st, AsOfView(conn, d), [s1], CFG, EVENTS, policies=policies(FixedPolicy(max_days=3)), overlays=None, strict=True, mode="backtest", default_overlays=default_overlays)
        decs.append(dec)
    h = hashlib.sha256()
    for d in decs:
        h.update(json.dumps(to_plain(d), sort_keys=True, default=str).encode())
    h.update(json.dumps(to_plain(st), sort_keys=True, default=str).encode())
    s2 = ScriptedStrategy(make_spec("dummy"), {DS[300].isoformat(): [{"symbol": "FIXCO", "stop": 159.115349}]})
    res = run_backtest(p, DS[295], DS[329], 1_000_000.0, [s2], policies(FixedPolicy(max_days=3)), CFG, EVENTS, default_overlays=default_overlays)
    h.update(json.dumps([dataclasses.asdict(t) for t in res.trades], default=str, indent=1).encode())
    h.update(json.dumps({d.isoformat(): v for d, v in res.equity_curve.items()}, indent=1).encode())
    h.update(json.dumps({dec.as_of.isoformat(): {"equity": res.equity_curve[dec.as_of], "cash": dec.cash_after} for dec in res.decisions}, indent=1).encode())
    h.update(json.dumps([{"date": dec.as_of.isoformat(), "strategy_id": b.strategy_id, "symbol": b.symbol, "reason": b.reason, "stage": b.stage} for dec in res.decisions for b in dec.blocked],
                        indent=1).encode())
    return h.hexdigest(), res


MASTER_DIGEST = "763ba4f23998c9919499a6549c77fe685a84d0f2e47857b32704e3b953377b7e"     # computed by the same procedure on origin/master b27431d, before any market-switch code existed


def test_a_run_with_default_overlays_off_is_byte_identical_to_master(monkeypatch):
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)
    d, res = digest([])
    assert d == MASTER_DIGEST
    assert res.manifest["overlays"] == []


def test_a_clear_switch_leaves_trades_equity_and_blocks_identical_only_the_logged_state_and_hashes_differ(monkeypatch):
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)
    _, off = digest([])
    _, on = digest(None)
    assert [dataclasses.asdict(t) for t in on.trades] == [dataclasses.asdict(t) for t in off.trades] and on.equity_curve == off.equity_curve
    assert on.manifest["overlays"] == describe_default_overlays(CFG) and on.manifest["overlays"][0]["id"] == "market_switch_v1"
    assert on.manifest["shared_config_hash"] != off.manifest["shared_config_hash"]
    assert on.manifest["overlays"][0]["params"] == {"trigger_sma_period": 200, "trigger_vix": 22.0, "reentry_sma_period": 20, "reentry_vix": 20.0, "reentry_sessions": 3}
    assert on.manifest["strategies"] == off.manifest["strategies"]                                  # strategy spec hashes are untouched


def test_daily_json_carries_the_state_only_when_the_overlay_ran(tmp_path):
    from stockbot.backtest.outputs import write_run_files
    _, on = digest(None)
    _, off = digest([])
    a, b = tmp_path / "on", tmp_path / "off"
    write_run_files(on, a)
    write_run_files(off, b)
    d_on, d_off = json.loads((a / "daily.json").read_text()), json.loads((b / "daily.json").read_text())
    k = next(iter(d_on))
    assert d_on[k]["market_switch"].keys() == {"state", "reason", "reentry_count"} and all("market_switch" not in v for v in d_off.values())
    assert {d: {x: y for x, y in v.items() if x != "market_switch"} for d, v in d_on.items()} == d_off
    assert (a / "blocked.json").read_bytes() == (b / "blocked.json").read_bytes()


def test_the_params_and_defaults_are_the_old_kill_switch_numbers():
    assert MarketSwitchParams.from_shared(CFG) == MarketSwitchParams(200, 22.0, 20, 20.0, 3)
