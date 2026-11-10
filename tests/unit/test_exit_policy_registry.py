"""stockbot.engine.exit_policies.registry: resolve(), the id formats, policies_for(), and the two wiring points (run_backtest, Book.from_strategies)."""
import pytest

from stockbot.engine.exit_policies.fixed_hold import FixedHold
from stockbot.engine.exit_policies.registry import UnknownExitPolicyError, policies_for, resolve
from stockbot.engine.exit_policies.trailing_stop import TrailingStop
from stockbot.engine.exit_policy import ExitPolicy
from stockbot.strategies.spec import StrategySpec
from tests.fixtures.dummies import FixedPolicy, make_spec
from tests.fixtures.own_policy import OwnExit


# ------------------------------------------------------------------ resolve
@pytest.mark.parametrize("pid,cls,attr,value", [
    ("fixed_hold_1", FixedHold, "hold_sessions", 1), ("fixed_hold_20", FixedHold, "hold_sessions", 20), ("fixed_hold_10000", FixedHold, "hold_sessions", 10000),
    ("trailing_pct_1", TrailingStop, "percent", 1), ("trailing_pct_10", TrailingStop, "percent", 10), ("trailing_pct_99", TrailingStop, "percent", 99),
])
def test_valid_ids_resolve_to_the_policy_with_those_parameters(pid, cls, attr, value):
    p = resolve(pid)
    assert isinstance(p, cls) and getattr(p, attr) == value and p.id == pid and isinstance(p, ExitPolicy)


MALFORMED = [
    "", " ", "fixed_hold", "fixed_hold_", "trailing_pct", "trailing_pct_", "fixed_hold_0", "fixed_hold_-1", "fixed_hold_+5", "fixed_hold_040", "fixed_hold_00", "fixed_hold_4.0",
    "fixed_hold_4e1", "fixed_hold_0x10", "fixed_hold_1_000", "fixed_hold_ 5", "fixed_hold_5 ", " fixed_hold_5", "fixed_hold_5\n", "fixed_hold_5\t", "fixed_hold_5x", "xfixed_hold_5",
    "fixed_hold_5_", "fixed_hold__5", "FIXED_HOLD_5", "Fixed_Hold_5", "fixed-hold-5", "fixedhold5", "fixed_hold_٥", "fixed_hold_５", "fixed_hold_5​",
    "trailing_pct_0", "trailing_pct_00", "trailing_pct_05", "trailing_pct_100", "trailing_pct_101", "trailing_pct_-5", "trailing_pct_+5", "trailing_pct_5.5", "trailing_pct_5.0",
    "trailing_pct_ 5", "trailing_pct_5 ", "trailing_pct_5\n", "trailing_pct_5%", "trailing_pct_５", "trailing_5", "TRAILING_PCT_5", "trailing_pct_1000",
    "unknown", "fixed", "fixed_hold_5,trailing_pct_5", "fixed_hold_5 trailing_pct_5",
]


@pytest.mark.parametrize("pid", MALFORMED)
def test_every_malformed_or_unknown_id_is_rejected_with_a_clear_error(pid):
    with pytest.raises(UnknownExitPolicyError) as e:
        resolve(pid)
    assert repr(pid) in str(e.value) and "fixed_hold_<N>" in str(e.value) and "trailing_pct_<P>" in str(e.value)
    assert isinstance(e.value, ValueError)


@pytest.mark.parametrize("bad", [None, 5, 5.0, b"fixed_hold_5", ("fixed_hold_5",), True])
def test_a_non_string_id_is_rejected(bad):
    with pytest.raises(UnknownExitPolicyError):
        resolve(bad)


def test_one_spelling_per_behaviour_and_the_id_is_deterministic():
    seen = {}
    for n in range(1, 301):
        p = resolve(f"fixed_hold_{n}")
        assert p.id == f"fixed_hold_{n}" and resolve(p.id).hold_sessions == n and seen.setdefault(p.hold_sessions, p.id) == p.id
    for q in range(1, 100):
        p = resolve(f"trailing_pct_{q}")
        assert p.id == f"trailing_pct_{q}" and p.percent == q
    assert resolve("fixed_hold_7").id == resolve("fixed_hold_7").id == FixedHold(7).id == "fixed_hold_7" and TrailingStop(9).id == "trailing_pct_9"


@pytest.mark.parametrize("bad", [0, -1, 2.0, "5", True, None])
def test_constructors_accept_only_a_positive_integer(bad):
    with pytest.raises(ValueError):
        FixedHold(bad)


@pytest.mark.parametrize("bad", [0, -1, 100, 150, 5.5, 5.0, "5", True, None])
def test_trailing_stop_constructor_accepts_only_an_integer_percent_1_to_99(bad):
    with pytest.raises(ValueError):
        TrailingStop(bad)


def test_the_policies_are_immutable():
    for p in (FixedHold(3), TrailingStop(5)):
        with pytest.raises(AttributeError):
            p.id = "x"
    with pytest.raises(AttributeError):
        FixedHold(3).hold_sessions = 4


# ------------------------------------------------------------------ the spec hash covers the policy id
def test_the_spec_hash_changes_when_the_policy_id_changes():
    a, b, c = (make_spec("alpha", pid).config_hash() for pid in ("fixed_hold_20", "fixed_hold_21", "trailing_pct_20"))
    assert len({a, b, c}) == 3 and make_spec("alpha", "fixed_hold_20").config_hash() == a


# ------------------------------------------------------------------ policies_for
def specs(*pids):
    return [make_spec(f"s{i}x", pid) for i, pid in enumerate(pids)]


def test_policies_for_builds_the_mapping_from_library_ids_keyed_by_policy_id():
    m = policies_for(specs("fixed_hold_5", "trailing_pct_8", "fixed_hold_5"))
    assert sorted(m) == ["fixed_hold_5", "trailing_pct_8"] and all(k == p.id for k, p in m.items())
    assert isinstance(m["fixed_hold_5"], FixedHold) and isinstance(m["trailing_pct_8"], TrailingStop)


def test_policies_for_resolves_library_and_strategy_owned_ids_together():
    own = OwnExit(2, "alpha_exit_2")
    m = policies_for(specs("fixed_hold_5", "alpha_exit_2"), extra=[own])
    assert m["alpha_exit_2"] is own and isinstance(m["fixed_hold_5"], FixedHold)


def test_policies_for_fails_loudly_on_an_unknown_id_naming_it():
    with pytest.raises(UnknownExitPolicyError, match="not_a_policy"):
        policies_for(specs("fixed_hold_5", "not_a_policy"))
    with pytest.raises(UnknownExitPolicyError, match="fixed_hold_040"):
        policies_for(specs("fixed_hold_040"))


def test_policies_for_fails_when_two_extra_policies_claim_one_id():
    with pytest.raises(ValueError, match="alpha_exit_2"):
        policies_for(specs("alpha_exit_2"), extra=[OwnExit(2, "alpha_exit_2"), OwnExit(3, "alpha_exit_2")])
    with pytest.raises(ValueError, match="alpha_exit_2"):                         # also when no spec uses it
        policies_for(specs("fixed_hold_5"), extra=[OwnExit(2, "alpha_exit_2"), OwnExit(3, "alpha_exit_2")])


@pytest.mark.parametrize("pid", ["fixed_hold_5", "trailing_pct_7", "fixed_hold_040", "fixed_hold_x", "trailing_pct_0", "fixed_hold_", "trailing_pct_zzz"])
def test_policies_for_rejects_a_strategy_owned_id_that_starts_with_a_library_prefix(pid):
    """One source per id: a valid library id would shadow the library; a look-alike would be confused with it."""
    with pytest.raises(ValueError, match=pid):
        policies_for(specs("fixed_hold_9"), extra=[OwnExit(2, pid)])


@pytest.mark.parametrize("bad", [object(), "alpha_exit_2", None])
def test_policies_for_rejects_an_extra_that_is_not_an_exit_policy(bad):
    with pytest.raises(ValueError):
        policies_for(specs("alpha_exit_2"), extra=[bad])


class NoId:
    id = ""
    initial_state = step = on_corporate_action = staticmethod(lambda *a: None)


def test_policies_for_rejects_an_extra_with_an_empty_id():
    with pytest.raises(ValueError):
        policies_for(specs("alpha_exit_2"), extra=[NoId()])


def test_policies_for_with_no_specs_is_empty_and_does_not_mutate_extra():
    assert policies_for([]) == {}
    extra = [OwnExit()]
    policies_for(specs("alpha_exit_2"), extra=extra)
    assert len(extra) == 1


# ------------------------------------------------------------------ the two wiring points
def test_run_backtest_builds_its_own_mapping_when_none_is_given_and_is_unchanged_when_given(tmp_path):
    from stockbot.backtest.runner import run_backtest
    from tests.fixtures import mini_lake
    from tests.fixtures.dummies import ScriptedStrategy
    from tests.fixtures.engine_run import CFG, EVENTS
    from tests.fixtures.policy_lakes import plain_lake
    ds = mini_lake.sessions()
    lake = plain_lake(tmp_path / "l.db")
    mk = lambda: ScriptedStrategy(make_spec("dummy", "fixed_hold_3"), {ds[300].isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
    a = run_backtest(lake, ds[296], ds[312], 1_000_000.0, [mk()], None, CFG, EVENTS)
    b = run_backtest(lake, ds[296], ds[312], 1_000_000.0, [mk()], {"fixed_hold_3": resolve("fixed_hold_3")}, CFG, EVENTS)
    assert [d.to_json() for d in a.decisions] == [d.to_json() for d in b.decisions] and a.trades and a.trades[0].exit_reason == "TIME_EXIT"
    with pytest.raises(UnknownExitPolicyError):
        run_backtest(lake, ds[296], ds[298], 1_000_000.0, [ScriptedStrategy(make_spec("dummy", "nope"), {})], None, CFG, EVENTS)


def test_the_live_book_is_built_from_the_specs():
    from stockbot.live.runner import Book, default_book
    from tests.fixtures.dummies import ScriptedStrategy
    s = ScriptedStrategy(make_spec("dummy", "trailing_pct_10"), {})
    book = Book.from_strategies([s])
    assert book.strategies == (s,) and list(book.policies) == ["trailing_pct_10"] and book.overlays == {}
    own = OwnExit()
    book2 = Book.from_strategies([ScriptedStrategy(make_spec("dummy", "alpha_exit_2"), {})], extra_policies=[own])
    assert book2.policies["alpha_exit_2"] is own
    assert default_book().strategies == () and default_book().policies == {}
    with pytest.raises(UnknownExitPolicyError):
        Book.from_strategies([ScriptedStrategy(make_spec("dummy", "alpha_exit_2"), {})])
