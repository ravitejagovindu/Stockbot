"""G3 - the fixture baseline: the hand-derived trade on the fixture lake, run through the engine (restructure Phase 10; before it was run through the old Simulator).

FIXCO on the 330-session fixture lake breaks out on session 300; the next open (177.0) fills with 0.10% slippage at 177.177; the stop is 159.115349 (the stop the old sizing
derived on this fixture, the golden master of that arithmetic, now simply the proposal's input); shares = floor(1,000,000 x 1% / (177.177 - 159.115349)) = 553; session 302 gaps down
and stops the position out at stop x (1 - 0.10%). Every number below is arithmetic done by hand. No real database is used."""
import sqlite3
from datetime import date

import pytest

from stockbot.risk.costs import CostModel
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.engine_run import CFG, policies, run_days
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()
SIG, ENTRY, CRASH = DS[mini_lake.BREAKOUT], DS[mini_lake.ENTRY], DS[mini_lake.CRASH]
G3_STOP = 159.115349
SLIP_IN, SLIP_OUT = CFG.execution.entry_slippage_pct / 100.0, CFG.execution.exit_slippage_pct / 100.0
COSTS = CostModel.from_shared(CFG.costs)


@pytest.fixture(scope="module")
def lake_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("lake") / "lake.db"
    _make(p)
    return p


def strat(stop, sid="dummy", day=SIG, symbol="FIXCO", **kw):
    return ScriptedStrategy(make_spec(sid), {day.isoformat(): [{"symbol": symbol, "stop": stop, **kw}]})


def days(a, b):
    return [d for d in DS if a <= d <= b]


def test_the_g3_trade_is_reproduced_by_the_engine(lake_path):
    decs, st = run_days(lake_path, days(DS[295], DS[306]), [strat(G3_STOP)], policies(FixedPolicy()))
    tickets = [t for d in decs for t in d.new_tickets]
    assert [(t.symbol, t.signal_date, t.stop) for t in tickets] == [("FIXCO", SIG, G3_STOP)]
    fills = [f for d in decs for f in d.fills]
    assert len(fills) == 1 and fills[0].date == ENTRY
    entry = 177.0 * (1 + SLIP_IN)
    assert fills[0].price == pytest.approx(entry, abs=1e-9)
    assert fills[0].shares == int(1_000_000.0 * CFG.portfolio_risk.max_loss_pct_per_trade / 100.0 // (entry - G3_STOP)) == 553
    (t,) = [c for d in decs for c in d.closed]
    assert (t.entry_date, t.exit_date, t.exit_reason) == (ENTRY, CRASH, "STOP_HIT")
    exit_price = G3_STOP * (1 - SLIP_OUT)
    (e,) = [x for d in decs for x in d.exits]
    assert e.price == pytest.approx(exit_price, abs=1e-9) and e.shares == 553 and e.closed
    gross = 553 * (exit_price - entry)
    costs = COSTS.buy_cost(entry * 553) + COSTS.sell_cost(exit_price * 553)
    assert t.gross_pnl == pytest.approx(gross) and t.costs == pytest.approx(costs) and t.net_pnl == pytest.approx(gross - costs)
    assert t.risk_inr == pytest.approx(553 * (entry - G3_STOP)) and t.gross_pnl / t.risk_inr < -1.0
    assert st.positions == () and st.cash == pytest.approx(1_000_000.0 + gross - costs) and st.realised_pnl_net == pytest.approx(gross - costs)


def test_this_module_does_not_depend_on_the_real_database():
    """F10 guard: no database path string and no session helper in this module (the real-database checks are in tests/data_integrity, STOCKBOT_DATA_TESTS=1)."""
    from pathlib import Path
    src = Path(__file__).read_text(encoding="utf-8")
    assert "finsight" + ".db" not in src.replace('"finsight" + ".db"', "") and "get_" + "session" not in src.replace('"get_" + "session"', "")
