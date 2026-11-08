"""Corporate actions on open positions inside the engine (ENGINE_CONTRACT section 7): equal to the legacy F3 module on a random grid, invariance of P&L through a split."""
import random
import sqlite3
from datetime import date

import pytest

from engine_core.lifecycle_rules import PosState
from stockbot.engine.corporate import apply_actions, due_actions
from stockbot.engine.corporate_action_events import apply_actions_to_position as legacy_apply
from stockbot.engine.corporate_action_events import due_actions as legacy_due
from stockbot.engine.types import Position
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.engine_run import policies, run_days
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()
ENTRY = mini_lake.ENTRY
SIG = DS[mini_lake.BREAKOUT]


def position(**kw):
    base = dict(position_id="p", strategy_id="s", symbol="AAA", sector=None, entry_date=date(2020, 1, 1), entry_price=100.0, initial_stop=90.0, live_stop=95.0, target=130.0,
                shares_initial=101.0, shares_remaining=101, risk_inr=1010.0, exit_policy_id="fixed", exit_state={"ref": 100.0}, highest_high=110.0, last_close=105.0)
    base.update(kw)
    return Position(**base)


def act(day, typ, num, den):
    return {"ex_date": day, "action_type": typ, "ratio_numerator": num, "ratio_denominator": den}


def test_bonus_with_a_fractional_remainder_pays_cash_in_lieu():
    p = position()
    out = apply_actions(p, [act(date(2020, 2, 3), "BONUS", 1, 2)], ex_price=70.0, policy=FixedPolicy())      # factor 2/3: 101 shares -> 151.5
    q = out.position
    assert q.shares_remaining == 151 and q.entry_price == pytest.approx(100.0 * 2 / 3) and q.live_stop == pytest.approx(95.0 * 2 / 3)
    assert out.fractional_cash == pytest.approx(0.5 * 70.0) and q.shares_initial == pytest.approx(101 * 1.5) and q.risk_inr == p.risk_inr
    assert q.exit_state["ref"] == pytest.approx(100.0 * 2 / 3) and q.ca_done == ("2020-02-03:BONUS",) and not q.hold


def test_unrescalable_action_puts_the_position_on_hold():
    p = position()
    out = apply_actions(p, [act(date(2020, 2, 3), "MERGER", None, None)], ex_price=70.0)
    assert out.position.hold and out.position.shares_remaining == 101 and out.position.entry_price == 100.0 and out.review == ("2020-02-03:MERGER",)
    bad = apply_actions(p, [act(date(2020, 2, 3), "SPLIT", None, None)], ex_price=70.0)
    assert bad.position.hold


def test_an_action_is_applied_once_and_dividends_are_ignored():
    a = [act(date(2020, 2, 3), "SPLIT", 1, 2), act(date(2020, 2, 4), "DIVIDEND", None, None)]
    assert [x["action_type"] for x in due_actions(a, date(2020, 1, 1), date(2020, 3, 1))] == ["SPLIT"]
    assert due_actions(a, date(2020, 1, 1), date(2020, 3, 1), already=["2020-02-03:SPLIT"]) == []
    assert due_actions(a, date(2020, 2, 3), date(2020, 3, 1)) == []                                      # not before/at the entry date
    assert due_actions(a, date(2020, 1, 1), date(2020, 2, 2)) == []                                      # not after the as-of date


def test_equal_to_the_legacy_f3_module_on_a_random_grid():
    rng = random.Random(11)
    kinds = ["SPLIT", "BONUS", "DIVIDEND", "MERGER", "RIGHTS"]
    for _ in range(400):
        sh = rng.randint(1, 5000)
        entry = rng.uniform(20, 900)
        stop = entry * rng.uniform(0.8, 0.98)
        hh = entry * rng.uniform(1.0, 1.3)
        acts = [act(date(2020, 2, 1 + i), rng.choice(kinds), rng.randint(1, 5), rng.randint(1, 6)) for i in range(rng.randint(0, 3))]
        ex_price = entry * rng.uniform(0.3, 1.0)
        p = position(entry_price=entry, initial_stop=stop, live_stop=stop, highest_high=hh, target=entry * 1.3, shares_remaining=sh, shares_initial=float(sh), last_close=entry)
        old = PosState(entry_price=entry, initial_stop=stop, live_stop=stop, target=entry * 1.3, highest_high=hh, shares_remaining=sh)
        new = apply_actions(p, [a for a in due_actions(acts, date(2020, 1, 1), date(2020, 3, 1))], ex_price)
        ref = legacy_apply(old, legacy_due(acts, date(2020, 1, 1), date(2020, 3, 1)), ex_price)
        assert new.position.shares_remaining == ref.pos.shares_remaining
        for f in ("entry_price", "initial_stop", "live_stop", "target", "highest_high"):
            assert getattr(new.position, f) == pytest.approx(getattr(ref.pos, f), rel=1e-12)
        assert new.fractional_cash == pytest.approx(ref.fractional_shares * ex_price, rel=1e-9, abs=1e-9)
        assert new.total_factor == pytest.approx(ref.total_factor) and list(new.applied) == ref.applied and list(new.review) == ref.review


def _split_lake(tmp_path, with_split):
    """FIXCO's raw prices halve (volume doubles) from session 305 on, with a 1:2 split in the log - or the same lake without either."""
    p = tmp_path / ("split.db" if with_split else "nosplit.db")
    _make(p, with_split=False)
    if with_split:
        ex = DS[305].isoformat()
        con = sqlite3.connect(p)
        con.execute("insert into corporate_actions_log (symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('FIXCO', ?, 'SPLIT', 1, 2, 'x', 'T1')", (ex,))
        con.execute("update market_data_lake set open_raw=open_raw/2, high_raw=high_raw/2, low_raw=low_raw/2, close_raw=close_raw/2, volume_raw=volume_raw*2 where symbol='FIXCO' and trade_date>=?", (ex,))
        con.commit(); con.close()
    return p


def test_a_split_inside_the_holding_period_leaves_pnl_and_r_unchanged(tmp_path):
    out = {}
    for flag in (False, True):
        lake = _split_lake(tmp_path, flag)
        s = ScriptedStrategy(make_spec("dummy", "timed"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
        decs, st = run_days(lake, DS[298:316], [s], policies(FixedPolicy(id="timed", max_days=8)))
        (t,) = [c for d in decs for c in d.closed]
        out[flag] = (t, [c for d in decs for c in d.corporate_actions_applied], st)
    plain, split = out[False][0], out[True][0]
    assert not out[False][1] and [c.key for c in out[True][1]] == [f"{DS[305].isoformat()}:SPLIT"] and out[True][1][0].factor == 0.5
    assert split.shares_initial == pytest.approx(2 * plain.shares_initial)                    # shares doubled
    assert split.entry_price == pytest.approx(plain.entry_price / 2)
    assert split.risk_inr == pytest.approx(plain.risk_inr)                                    # R is invariant
    assert split.gross_pnl == pytest.approx(plain.gross_pnl) and split.costs == pytest.approx(plain.costs, rel=1e-6)
    assert split.net_pnl == pytest.approx(plain.net_pnl, rel=1e-6) and split.exit_date == plain.exit_date
    assert out[True][2].cash == pytest.approx(out[False][2].cash, rel=1e-9)


def test_the_baseline_helper_rebases_for_a_split_exactly_like_decide(tmp_path):
    from stockbot.backtest.runner import run_backtest
    from stockbot.data.asof import AsOfView
    from stockbot.data.lake import open_lake
    from stockbot.engine.path import simulate_ticket
    from tests.fixtures.engine_run import CFG, EVENTS
    lake = _split_lake(tmp_path, True)
    pol = policies(FixedPolicy(id="timed", max_days=8))
    s = ScriptedStrategy(make_spec("dummy", "timed"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
    window = DS[298:316]
    bt = run_backtest(lake, window[0], window[-1], 1_000_000.0, [s], pol, CFG, EVENTS)
    ticket = next(t for d in bt.decisions for t in d.new_tickets)
    conn = open_lake(lake)
    trade, exits, why = simulate_ticket(ticket, window, lambda d: AsOfView(conn, d), shared_config=CFG, policy=pol["timed"], equity=1_000_000.0)
    assert why == "CLOSED" and trade == bt.trades[0] and trade.shares_initial == pytest.approx(2 * 367)
