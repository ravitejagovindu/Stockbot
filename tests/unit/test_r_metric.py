"""F1 — explicit gross / net / after-tax R metrics (single definition in stockbot.validation.trade_metrics)."""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from stockbot.risk.r_metrics import add_r_columns, compute_trade_r


def test_compute_trade_r_with_partial_exit_hand_computed():
    # entry 100, stop 90, 100 shares -> initial risk 1,000 INR.
    # exits: 12 sh @110 (partial, +120) then 88 sh @105 (+440) -> gross 560.
    # costs 50 -> net 510; tax 102 -> after-tax 408.
    r = compute_trade_r(
        entry_price=100.0, stop=90.0, shares_initial=100,
        pnl_gross=560.0, pnl_net=510.0, tax_est=102.0,
    )
    assert r["gross_r"] == pytest.approx(0.56)
    assert r["net_r"] == pytest.approx(0.51)
    assert r["net_r_after_tax"] == pytest.approx(0.408)
    assert r["risk_inr"] == pytest.approx(1000.0)


def test_risk_inr_override_survives_price_rebasing():
    # After a split the entry/stop/shares are rebased, but R must use the INR risk recorded at entry.
    r = compute_trade_r(
        entry_price=50.0, stop=45.0, shares_initial=200,
        pnl_gross=560.0, pnl_net=510.0, tax_est=0.0, risk_inr=1000.0,
    )
    assert r["net_r"] == pytest.approx(0.51)


def test_dataframe_and_scalar_agree():
    df = pd.DataFrame([{
        "entry_price": 100.0, "stop": 90.0, "shares": 100,
        "pnl_gross": 560.0, "pnl_net": 510.0, "tax_est": 102.0,
    }])
    out = add_r_columns(df)
    s = compute_trade_r(entry_price=100.0, stop=90.0, shares_initial=100,
                        pnl_gross=560.0, pnl_net=510.0, tax_est=102.0)
    for k in ("gross_r", "net_r", "net_r_after_tax"):
        assert out.iloc[0][k] == pytest.approx(s[k])


def _sim_fixture(session):
    """Same synthetic series as the sim-vs-live golden master (entry 102 on day 10, gap-stop on day 17)."""
    from data.db.models import MarketDataLake, SharesOutstanding
    from tests.integration.test_sim_vs_live_rules import _get_base_config

    cfg = _get_base_config()
    d0 = date(2024, 1, 1)
    dates = [d0 + timedelta(days=i) for i in range(25)]
    for d in dates:
        session.add(MarketDataLake(symbol="NIFTY50_INDEX", trade_date=d, open_raw=22000.0, high_raw=22100.0,
                                   low_raw=21900.0, close_raw=22050.0, volume_raw=1000000, exchange="NSE"))
        session.add(MarketDataLake(symbol="INDIA_VIX", trade_date=d, open_raw=14.0, high_raw=14.5,
                                   low_raw=13.5, close_raw=14.0, volume_raw=0, exchange="NSE"))
    session.add(SharesOutstanding(symbol="SYNTH", effective_date=dates[0], shares_count=500_000_000))
    prices = [
        (95.0, 100.0, 93.0, 96.0), (96.0, 135.0, 94.0, 97.0), (97.0, 100.0, 95.0, 98.0),
        (98.0, 100.0, 96.0, 99.0), (99.0, 100.0, 97.0, 100.0), (99.0, 101.0, 97.0, 100.0),
        (98.0, 101.0, 96.0, 99.0), (99.0, 101.0, 97.0, 100.0), (100.0, 102.0, 98.0, 101.0),
        (101.0, 102.0, 99.0, 102.0), (102.0, 107.0, 101.0, 106.0), (106.0, 110.0, 105.0, 109.0),
        (109.0, 112.0, 108.0, 111.0), (111.0, 114.0, 110.0, 113.0), (113.0, 116.0, 112.0, 115.0),
        (115.0, 117.0, 114.0, 116.0), (116.0, 118.0, 115.0, 117.0), (94.0, 95.0, 90.0, 91.0),
    ]
    for i, (o, h, l, c) in enumerate(prices):
        session.add(MarketDataLake(symbol="SYNTH", trade_date=dates[i], open_raw=o, high_raw=h,
                                   low_raw=l, close_raw=c, volume_raw=5_000_000, exchange="NSE"))
    session.flush()
    return cfg, dates


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from data.db.connection import Base
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


def test_simulator_writes_explicit_r_columns_net_differs_from_gross(session):
    from backtest.simulator import Simulator

    cfg, dates = _sim_fixture(session)
    cfg["costs"]["stcg_tax_pct"] = 20.0
    res = Simulator(cfg, session).run(dates[0], dates[17], 1_000_000.0)
    t = res.trades.iloc[0]
    for col in ("risk_inr", "gross_r", "net_r", "net_r_after_tax"):
        assert col in res.trades.columns, col
    assert t["costs"] > 0
    assert t["risk_inr"] == pytest.approx(t["shares"] * (t["entry_price"] - t["stop"]))
    assert t["gross_r"] == pytest.approx(t["pnl_gross"] / t["risk_inr"])
    assert t["net_r"] == pytest.approx(t["pnl_net"] / t["risk_inr"])
    assert t["net_r"] < t["gross_r"]
    assert t["gross_r"] == pytest.approx(t["realized_r"])  # deprecated alias


def _trades(net_equals_gross: bool) -> pd.DataFrame:
    rows = []
    for i in range(6):
        gross = 0.5 - 0.1 * i
        rows.append({
            "position_id": i, "symbol": "X", "entry_date": f"2020-01-{i + 1:02d}", "exit_date": f"2020-02-{i + 1:02d}",
            "window": "W1 (2020-21)", "costs": 100.0, "gross_r": gross,
            "net_r": gross if net_equals_gross else gross - 0.05,
        })
    return pd.DataFrame(rows)


def test_select_candidate_rejects_missing_r_column():
    from scripts.provenance.select_candidate import require_r_columns

    df = _trades(False).drop(columns=["net_r"])
    with pytest.raises(ValueError, match="net_r"):
        require_r_columns(df)


def test_select_candidate_rejects_legacy_file_without_gross_r():
    from scripts.provenance.select_candidate import require_r_columns

    df = _trades(False).drop(columns=["gross_r"])
    with pytest.raises(ValueError, match="gross_r"):
        require_r_columns(df)


def test_select_candidate_rejects_net_equal_gross_with_costs():
    from scripts.provenance.select_candidate import require_r_columns

    with pytest.raises(ValueError, match="identical"):
        require_r_columns(_trades(True))
    require_r_columns(_trades(False))  # ok


def test_max_t_series_builders_require_explicit_column():
    from stockbot.validation.max_t_bootstrap import build_weekly_actual_series

    df = _trades(False).drop(columns=["net_r"])
    with pytest.raises(ValueError, match="net_r"):
        build_weekly_actual_series(df)


def test_baseline_and_simulator_share_the_same_r_function(session):
    """Same inputs -> same R whether produced by the Simulator row or the baseline's add_r_columns path."""
    from backtest.simulator import Simulator

    cfg, dates = _sim_fixture(session)
    res = Simulator(cfg, session).run(dates[0], dates[17], 1_000_000.0)
    legacy_shape = res.trades.drop(columns=["risk_inr", "gross_r", "net_r", "net_r_after_tax"])
    again = add_r_columns(legacy_shape)  # what scripts/redesigned_random_baseline.load_actual_trades does
    for k in ("gross_r", "net_r", "net_r_after_tax"):
        assert again[k].iloc[0] == pytest.approx(res.trades[k].iloc[0])
