"""Isolation between strategies on different policies, a position keeps its own policy id, the strategy-owned policy boundary, lookahead."""
import ast
from pathlib import Path

import pytest

from stockbot.engine.exit_policies.registry import policies_for
from stockbot.engine.exit_policy import ExitPolicy
from tests.fixtures import boundaries as B
from tests.fixtures import mini_lake
from tests.fixtures.dummies import ScriptedStrategy, make_spec
from tests.fixtures.engine_run import EVENTS, run_days
from tests.fixtures.own_policy import OwnExit
from tests.fixtures.policy_lakes import lake_with_future_changed, plain_lake

ROOT = Path(__file__).resolve().parents[2]
DS = mini_lake.sessions()
SIG, ENTRY = mini_lake.BREAKOUT, mini_lake.ENTRY
EV = EVENTS.__class__(sectors={"FIXCO": "IT", "OTHERCO": "FIN"})


def strat(sid, pid, symbol="FIXCO", stop=150.0):
    return ScriptedStrategy(make_spec(sid, pid), {DS[SIG].isoformat(): [{"symbol": symbol, "stop": stop}]})


def window(a, b):
    return [d for d in DS if DS[a] <= d <= DS[b]]


@pytest.fixture(scope="module")
def two_symbol_lake(tmp_path_factory):
    """The fixture lake plus OTHERCO: a copy of FIXCO's bars scaled by 0.5 (same shape, so it also breaks out and is eligible)."""
    import sqlite3
    p = plain_lake(tmp_path_factory.mktemp("two") / "l.db")
    con = sqlite3.connect(p)
    cols = [r[1] for r in con.execute("pragma table_info(market_data_lake)")]
    rows = con.execute("select * from market_data_lake where symbol='FIXCO'").fetchall()
    idx = {c: i for i, c in enumerate(cols)}
    con.execute("create temp table t as select * from market_data_lake where 0")
    for r in rows:
        r = list(r)
        r[idx["symbol"]] = "OTHERCO"
        for c in ("open_raw", "high_raw", "low_raw", "close_raw"):
            r[idx[c]] = r[idx[c]] * 0.5
        if "id" in idx:
            r[idx["id"]] = None
        con.execute(f"insert into market_data_lake values ({','.join('?' * len(cols))})", r)
    con.commit(); con.close()
    return p


def test_two_strategies_on_different_policies_and_symbols_do_not_affect_each_other(two_symbol_lake):
    a, b = strat("a_one", "fixed_hold_3"), strat("b_two", "trailing_pct_5", "OTHERCO", stop=75.0)
    w = window(SIG - 2, ENTRY + 8)
    both, st = run_days(two_symbol_lake, w, [a, b], policies_for([a.spec, b.spec]), events=EV)
    alone_a, _ = run_days(two_symbol_lake, w, [strat("a_one", "fixed_hold_3")], policies_for([a.spec]), events=EV)
    alone_b, _ = run_days(two_symbol_lake, w, [strat("b_two", "trailing_pct_5", "OTHERCO", stop=75.0)], policies_for([b.spec]), events=EV)
    mine = lambda decs, sid: [(d.as_of, e.symbol, e.reason, e.price, e.shares) for d in decs for e in d.exits if e.strategy_id == sid]
    fills = lambda decs, sid: [(d.as_of, f.symbol, f.price, f.shares) for d in decs for f in d.fills if f.strategy_id == sid]
    assert mine(both, "a_one") == mine(alone_a, "a_one") and mine(both, "b_two") == mine(alone_b, "b_two")
    assert fills(both, "a_one") == fills(alone_a, "a_one") and fills(both, "b_two") == fills(alone_b, "b_two") and fills(both, "a_one") and fills(both, "b_two")
    assert {e[2] for e in mine(both, "a_one")} == {"TIME_EXIT"} and {e[2] for e in mine(both, "b_two")} == {"STOP_HIT"}        # each policy did its own thing


def test_a_position_keeps_its_own_policy_id_even_if_the_mapping_grows(two_symbol_lake):
    a, b = strat("a_one", "fixed_hold_20"), strat("b_two", "trailing_pct_5", "OTHERCO", stop=75.0)
    decs, st = run_days(two_symbol_lake, window(SIG - 2, ENTRY), [a, b], policies_for([a.spec, b.spec]), events=EV)
    assert {p.strategy_id: p.exit_policy_id for p in st.positions} == {"a_one": "fixed_hold_20", "b_two": "trailing_pct_5"}
    assert st.positions[0].exit_state == {} or "highest_close" not in dict(next(p for p in st.positions if p.strategy_id == "a_one").exit_state)


def test_a_position_whose_policy_is_missing_from_the_mapping_fails_loudly(tmp_path):
    from stockbot.engine.decide import EngineInputError
    lake = plain_lake(tmp_path / "l.db")
    a = strat("a_one", "fixed_hold_20")
    _, st = run_days(lake, window(SIG - 2, ENTRY), [a], policies_for([a.spec]))
    other = strat("a_one", "fixed_hold_21")
    with pytest.raises(EngineInputError, match="fixed_hold_20"):
        run_days(lake, [DS[ENTRY + 1]], [other], policies_for([other.spec]), state=st)             # a closed-out strategy with open positions: documented limitation


def test_lookahead_changing_every_later_bar_does_not_change_earlier_decisions(tmp_path):
    T = DS[ENTRY + 3]
    a, b = plain_lake(tmp_path / "a.db"), lake_with_future_changed(tmp_path / "b.db", T)
    for pid in ("fixed_hold_3", "trailing_pct_5"):
        s1, s2 = strat("dummy", pid), strat("dummy", pid)
        ra = run_days(a, window(SIG - 2, ENTRY + 3), [s1], policies_for([s1.spec]))
        rb = run_days(b, window(SIG - 2, ENTRY + 3), [s2], policies_for([s2.spec]))
        assert [d.to_json() for d in ra[0]] == [d.to_json() for d in rb[0]] and ra[1].to_json() == rb[1].to_json() and any(d.fills for d in ra[0])


# ------------------------------------------------------------------ boundary: strategy-owned policy and other strategies
def imports_of(path: Path):
    out = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


def test_the_test_policy_imports_only_the_interface_types_and_satisfies_the_interface():
    mods = imports_of(ROOT / "tests" / "fixtures" / "own_policy.py")
    assert {m for m in mods if m.startswith("stockbot")} == {"stockbot.engine.exit_policy"} and isinstance(OwnExit(), ExitPolicy)


def test_a_strategy_folder_with_its_own_policy_passes_the_boundary_scan_and_one_with_a_forbidden_import_fails(tmp_path):
    """Seed real trees: stockbot/strategies/alpha/exits.py is the test policy's code; a second tree adds forbidden imports."""
    ok = tmp_path / "ok"
    (ok / "stockbot" / "strategies" / "alpha").mkdir(parents=True)
    src = (ROOT / "tests" / "fixtures" / "own_policy.py").read_text(encoding="utf-8")
    (ok / "stockbot" / "strategies" / "alpha" / "exits.py").write_text(src)
    assert B.check(ok) == set()
    for bad_import, rule in [("from stockbot.engine.exit_policies.registry import resolve", "strategies may not import engine"),
                             ("from stockbot.engine.exit_policies import fixed_hold", "strategies may not import engine"),
                             ("from stockbot.engine.stepping import step_position", "strategies may not import engine"),
                             ("from stockbot.engine.types import Position", "strategies may not import engine"),
                             ("from stockbot.engine import decide", "strategies may not import engine"),
                             ("import stockbot.engine.decide", "strategies may not import engine"),
                             ("from stockbot.strategies.beta.exits import OwnExit", "a strategy may not import another strategy"),
                             ("from stockbot.backtest.runner import run_backtest", "strategies may not import backtest"),
                             ("import sqlite3", "database library inside strategies"),
                             ("import requests", "network library inside strategies")]:
        bad = tmp_path / ("bad_" + str(abs(hash(bad_import))))
        (bad / "stockbot" / "strategies" / "alpha").mkdir(parents=True)
        (bad / "stockbot" / "strategies" / "alpha" / "exits.py").write_text(src + "\n" + bad_import + "\n")
        assert any(rule in r for _, _, r in B.check(bad)), (bad_import, B.check(bad))


def test_a_strategy_cannot_import_another_strategy_even_with_a_policy_inside(tmp_path):
    root = tmp_path / "t"
    for name, body in (("alpha", "from stockbot.strategies.beta.exits import X\n"), ("beta", "class X: ...\n")):
        (root / "stockbot" / "strategies" / name).mkdir(parents=True)
        (root / "stockbot" / "strategies" / name / "exits.py").write_text(body)
    assert {r for _, _, r in B.check(root)} == {"a strategy may not import another strategy"}


def test_the_library_imports_only_the_interface_file_and_the_standard_library():
    lib = ROOT / "stockbot" / "engine" / "exit_policies"
    for f in lib.glob("*.py"):
        stock = {m for m in imports_of(f) if m.split(".")[0] == "stockbot"}
        relative = [n for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))) if isinstance(n, ast.ImportFrom) and n.level]
        assert not relative
        assert stock <= {"stockbot.engine.exit_policy", "stockbot.engine.exit_policies.fixed_hold", "stockbot.engine.exit_policies.trailing_stop"} and \
            (f.name == "registry.py" or stock <= {"stockbot.engine.exit_policy"}), (f.name, stock)
