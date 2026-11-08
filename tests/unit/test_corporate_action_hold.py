"""F3 — splits/bonuses (and unhandled actions) during an open position; Simulator and PLM must agree."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from data.db.connection import Base
from data.db.models import (
    ActivePosition, CorporateActionsLog, MarketDataLake, SharesOutstanding, TradeAnalyticsLog,
)
from tests.integration.test_sim_vs_live_rules import _get_base_config

D0 = date(2024, 1, 1)
DATES = [D0 + timedelta(days=i) for i in range(25)]
# (open, high, low, close); entry fills at 102 on index 10; gap-down stop-out on index 17.
PRICES = [
    (95.0, 100.0, 93.0, 96.0), (96.0, 135.0, 94.0, 97.0), (97.0, 100.0, 95.0, 98.0),
    (98.0, 100.0, 96.0, 99.0), (99.0, 100.0, 97.0, 100.0), (99.0, 101.0, 97.0, 100.0),
    (98.0, 101.0, 96.0, 99.0), (99.0, 101.0, 97.0, 100.0), (100.0, 102.0, 98.0, 101.0),
    (101.0, 102.0, 99.0, 102.0), (102.0, 107.0, 101.0, 106.0), (106.0, 110.0, 105.0, 109.0),
    (109.0, 112.0, 108.0, 111.0), (111.0, 114.0, 110.0, 113.0), (113.0, 116.0, 112.0, 115.0),
    (115.0, 117.0, 114.0, 116.0), (116.0, 118.0, 115.0, 117.0), (94.0, 95.0, 90.0, 91.0),
]
EX_IDX = 13  # ex-date index inside the holding period (entry idx 10, exit idx 17)


@pytest.fixture
def session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


def _build(session, action=None, ex_idx=EX_IDX, factor=1.0):
    """Seed index data + SYNTH. If ``action`` is given, raw prices from ex_idx on are multiplied by ``factor`` and the
    action is logged; with action=None the raw series is the unsplit control."""
    cfg = _get_base_config()
    cfg["costs"]["stcg_tax_pct"] = 0.0
    for d in DATES:
        session.add(MarketDataLake(symbol="NIFTY50_INDEX", trade_date=d, open_raw=22000.0, high_raw=22100.0,
                                   low_raw=21900.0, close_raw=22050.0, volume_raw=1000000, exchange="NSE"))
        session.add(MarketDataLake(symbol="INDIA_VIX", trade_date=d, open_raw=14.0, high_raw=14.5,
                                   low_raw=13.5, close_raw=14.0, volume_raw=0, exchange="NSE"))
    session.add(SharesOutstanding(symbol="SYNTH", effective_date=DATES[0], shares_count=500_000_000))
    for i, (o, h, l, c) in enumerate(PRICES):
        f = factor if (action is not None and i >= ex_idx) else 1.0
        session.add(MarketDataLake(symbol="SYNTH", trade_date=DATES[i], open_raw=o * f, high_raw=h * f,
                                   low_raw=l * f, close_raw=c * f, volume_raw=5_000_000, exchange="NSE"))
    if action is not None:
        session.add(CorporateActionsLog(symbol="SYNTH", ex_date=DATES[ex_idx], action_type=action[0],
                                        ratio_numerator=action[1], ratio_denominator=action[2]))
    session.flush()
    return cfg


def _run(session, cfg):
    from backtest.simulator import Simulator
    return Simulator(cfg, session).run(DATES[0], DATES[17], 1_000_000.0)


def _control(session):
    cfg = _build(session)
    return _run(session, cfg).trades.iloc[0]


def _fresh_session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


# --------------------------------------------------------------------------- pure math
def test_rescale_for_action_split_scales_prices_and_shares():
    from engine_core.lifecycle_rules import PosState, rescale_for_action

    p = PosState(entry_price=200.0, initial_stop=190.0, live_stop=195.0, target=230.0, highest_high=210.0,
                 shares_remaining=10, days_held=3, last_partial_rr=1.0, partial_count=1)
    q, frac = rescale_for_action(p, 0.5, ex_price=100.0)
    assert (q.entry_price, q.initial_stop, q.live_stop, q.target, q.highest_high) == (100.0, 95.0, 97.5, 115.0, 105.0)
    assert q.shares_remaining == 20 and frac == 0
    assert q.days_held == 3 and q.last_partial_rr == 1.0 and q.partial_count == 1
    assert q.one_r * q.shares_remaining == pytest.approx(p.one_r * p.shares_remaining)


def test_rescale_for_action_fractional_shares_go_to_cash_in_lieu():
    from engine_core.lifecycle_rules import PosState, rescale_for_action

    p = PosState(entry_price=100.0, initial_stop=90.0, live_stop=90.0, target=130.0, highest_high=100.0,
                 shares_remaining=9)
    f = 5.0 / 7.0  # 2:5 bonus -> 9 / (5/7) = 12.6 shares
    q, frac = rescale_for_action(p, f, ex_price=70.0)
    assert q.shares_remaining == 12
    assert frac == pytest.approx(0.6)


# --------------------------------------------------------------------------- Simulator
@pytest.mark.parametrize("action,factor", [(("SPLIT", 1.0, 2.0), 0.5), (("BONUS", 1.0, 1.0), 0.5)])
def test_simulator_pure_split_or_bonus_does_not_change_outcome(action, factor):
    ctl = _control(_fresh_session())
    s2 = _fresh_session()
    cfg = _build(s2, action=action, factor=factor)
    res = _run(s2, cfg)
    assert len(res.trades) == 1, "false stop-out / lost trade on the ex-date"
    t = res.trades.iloc[0]
    assert t["exit_date"] == ctl["exit_date"]
    assert t["exit_reason"] == ctl["exit_reason"]
    assert t["pnl_gross"] == pytest.approx(ctl["pnl_gross"], rel=1e-9)
    assert t["gross_r"] == pytest.approx(ctl["gross_r"], rel=1e-9)
    assert t["net_r"] == pytest.approx(ctl["net_r"], rel=1e-6)
    assert t["risk_inr"] == pytest.approx(ctl["risk_inr"], rel=1e-9)
    assert not bool(t["excluded_ca"])


def test_simulator_flags_unhandled_action_and_metrics_exclude_it():
    s2 = _fresh_session()
    cfg = _build(s2)
    s2.add(CorporateActionsLog(symbol="SYNTH", ex_date=DATES[EX_IDX], action_type="RIGHTS",
                               ratio_numerator=1.0, ratio_denominator=4.0))
    s2.flush()
    res = _run(s2, cfg)
    t = res.trades.iloc[0]
    assert bool(t["excluded_ca"])
    from stockbot.validation.trade_metrics import metrics_from_trades
    assert metrics_from_trades(res.trades, 1_000_000.0).get("n_trades", 0) == 0


# --------------------------------------------------------------------------- live manager (PLM) parity
def _plm_run(session, cfg, entry_price, stop, shares):
    from engine_core.position_lifecycle import PositionLifecycleManager

    session.add(ActivePosition(
        symbol="SYNTH", entry_date=DATES[10], entry_price=entry_price, shares=shares, original_shares=shares,
        shares_remaining=shares, initial_stop_loss=stop, live_stop_loss=stop, initial_resistance_target=135.0,
        projected_rr=2.0, days_held=0, highest_high_since_breakout=entry_price,
        account_equity_at_entry=1_000_000.0, stop_a_at_entry=stop, stop_b_at_entry=stop, mode="PAPER",
        risk_inr=shares * (entry_price - stop)))
    session.flush()
    plm = PositionLifecycleManager(cfg, session)
    closed_on, flags_seen = None, []
    for d in DATES[10:18]:
        for u in plm.process_all(d, kill_switch_active=False):
            flags_seen.extend(u.flags)
            if "POSITION_CLOSED" in u.flags:
                closed_on = d
    return closed_on, flags_seen


def test_plm_split_during_hold_matches_simulator_and_unsplit_control():
    ctl = _control(_fresh_session())
    s2 = _fresh_session()
    cfg = _build(s2, action=("SPLIT", 1.0, 2.0), factor=0.5)
    sim_t = _run(s2, cfg).trades.iloc[0]

    s3 = _fresh_session()
    cfg3 = _build(s3, action=("SPLIT", 1.0, 2.0), factor=0.5)
    closed_on, flags = _plm_run(s3, cfg3, entry_price=float(ctl["entry_price"]), stop=float(ctl["stop"]),
                                shares=int(ctl["shares"]))
    assert closed_on == sim_t["exit_date"] == ctl["exit_date"]  # not closed on the ex-date
    assert not any("GAP_THROUGH_STOP" in f for f in flags if closed_on != DATES[17])
    logged = s3.query(TradeAnalyticsLog).all()
    assert len(logged) == 1
    assert logged[0].pnl_gross == pytest.approx(sim_t["pnl_gross"], rel=1e-9)
    assert logged[0].realized_rr == pytest.approx(ctl["gross_r"], rel=1e-9)


def test_original_scratch_repro_is_now_a_regression_test():
    """Held position + 1:2 split used to return STOP_HIT / GAP_THROUGH_STOP on the ex-date."""
    s = _fresh_session()
    cfg = _build(s, action=("SPLIT", 1.0, 2.0), factor=0.5)
    ctl_entry, ctl_stop = 102.0, 95.0
    closed_on, flags = _plm_run(s, cfg, ctl_entry, ctl_stop, 100)
    assert closed_on != DATES[EX_IDX]
    assert closed_on == DATES[17]


def test_f3_migration_adds_columns_idempotently(tmp_path):
    from data.db.migration_f3_corporate_actions import run_migration

    eng = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE active_positions (id INTEGER PRIMARY KEY, symbol TEXT)"))
        c.execute(text("CREATE TABLE trade_analytics_log (id INTEGER PRIMARY KEY, symbol TEXT)"))
    first = run_migration(eng)
    assert "active_positions.risk_inr" in first and "trade_analytics_log.excluded_ca" in first
    assert run_migration(eng) == []


def test_schema_sql_contains_f3_columns():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[2] / "data" / "db" / "schema.sql").read_text(encoding="utf-8")
    for col in ("applied_corp_actions", "manual_review_ca", "excluded_ca", "risk_inr"):
        assert col in sql
