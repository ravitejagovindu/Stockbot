"""F4 — backtests must not read or write the production regime_state and must refuse the live DB by default."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from stockbot.data.db.connection import Base
from stockbot.data.db.models import RegimeState
from tests.unit.test_r_metric import _sim_fixture


@pytest.fixture
def session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


def _regime_dump(s):
    return s.execute(text(
        "select eval_date, kill_switch_active, reentry_consecutive_count, nifty_close from regime_state order by id"
    )).fetchall()


def test_backtest_does_not_write_regime_state(session):
    from backtest.simulator import Simulator

    cfg, dates = _sim_fixture(session)
    session.add(RegimeState(eval_date=dates[0].replace(year=2023), kill_switch_active=False, nifty_close=1.0,
                            reentry_consecutive_count=0))
    session.flush()
    before = _regime_dump(session)
    Simulator(cfg, session).run(dates[0], dates[17], 1_000_000.0)
    assert _regime_dump(session) == before  # row count AND content unchanged


def test_result_independent_of_preexisting_regime_state(session):
    from backtest.simulator import Simulator

    cfg, dates = _sim_fixture(session)
    r1 = Simulator(cfg, session).run(dates[0], dates[17], 1_000_000.0)
    assert len(r1.trades) == 1

    # A stale "kill switch active" row just before the window must not change the backtest.
    session.add(RegimeState(eval_date=dates[0].replace(year=2023, month=12, day=31), kill_switch_active=True,
                            nifty_close=1.0, reentry_consecutive_count=0))
    session.flush()
    r2 = Simulator(cfg, session).run(dates[0], dates[17], 1_000_000.0)
    assert r1.trades.drop(columns=[]).equals(r2.trades)
    assert (r1.equity == r2.equity).all()


def test_regime_seed_is_recorded(session):
    from backtest.simulator import Simulator

    cfg, dates = _sim_fixture(session)
    r = Simulator(cfg, session).run(dates[0], dates[17], 1_000_000.0)
    seed = r.regime_seed
    assert set(seed) >= {"kill_switch_active", "reentry_consecutive_count", "derivation"}
    assert "warm-up" in seed["derivation"] or "explicit" in seed["derivation"]

    r2 = Simulator(cfg, session).run(dates[0], dates[17], 1_000_000.0,
                                     regime_seed={"kill_switch_active": False, "reentry_consecutive_count": 0})
    assert r2.regime_seed["derivation"].startswith("explicit")


def test_regime_filter_persist_false_never_touches_table(session):
    from engine_core.regime_filter import RegimeFilter

    cfg, dates = _sim_fixture(session)
    rf = RegimeFilter(cfg, session, persist=False)
    for d in dates[:6]:
        rf.evaluate(d)
    assert _regime_dump(session) == []


def test_simulator_refuses_live_db_without_override(tmp_path, monkeypatch):
    import stockbot.data.db.connection as conn
    from backtest.simulator import Simulator
    from tests.unit.test_r_metric import _sim_fixture as fx

    db = tmp_path / "live_like.db"
    url = f"sqlite:///{db.as_posix()}"
    monkeypatch.setattr(conn, "DATABASE_URL", url)
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    cfg, dates = fx(s)
    s.commit()

    with pytest.raises(RuntimeError, match="live database"):
        Simulator(cfg, s)

    sim = Simulator(cfg, s, allow_live_db=True)
    res = sim.run(dates[0], dates[17], 1_000_000.0)
    assert len(res.trades) == 1
    # query_only is switched back off after the run so ordinary sessions keep working
    assert s.execute(text("PRAGMA query_only")).scalar() == 0
    s.close()
    eng.dispose()
