"""stockbot.validation.benchmark_alpha (shared-rules B1/B3): cash-credited strategy equity, alpha raw and cash-credited, illustrative after-tax alpha, implied annual return."""
import numpy as np
import pandas as pd
import pytest

from stockbot.validation import benchmark_alpha as BA

RF = 6.5
D = 252


def _idx(n, start="2020-01-01"):
    return pd.bdate_range(start, periods=n).date


def test_all_cash_flat_equity_earns_the_risk_free_rate():
    n = D + 1
    eq = pd.Series(1_000_000.0, index=_idx(n))
    cash = eq.copy()
    adj = BA.cash_credited_equity(eq, cash, RF)
    assert adj.iloc[0] == 1_000_000.0
    assert adj.iloc[-1] == pytest.approx(1_000_000.0 * (1 + RF / 100 / D) ** D, rel=1e-12)


def test_fully_invested_is_unchanged_and_input_is_not_modified():
    eq = pd.Series(np.linspace(1e6, 1.2e6, 30), index=_idx(30))
    before = eq.copy()
    adj = BA.cash_credited_equity(eq, pd.Series(0.0, index=eq.index), RF)
    pd.testing.assert_series_equal(adj, eq.astype(float), check_names=False)
    pd.testing.assert_series_equal(eq, before)            # interest is applied after the fact: the input (the engine's equity) is never touched


def test_interest_uses_the_previous_close_cash_not_the_same_day():
    idx = _idx(3)
    eq = pd.Series([1000.0, 1000.0, 1000.0], index=idx)
    cash = pd.Series([0.0, 1000.0, 0.0], index=idx)       # cash is idle at the close of day 1 only
    adj = BA.cash_credited_equity(eq, cash, RF)
    rf = RF / 100 / D
    assert adj.iloc[1] == pytest.approx(1000.0)            # day 1 earns on day 0's cash (none)
    assert adj.iloc[2] == pytest.approx(1000.0 * (1 + rf))  # day 2 earns on day 1's cash (all of it)


def test_cash_share_is_clipped_and_aligned():
    idx = _idx(3)
    eq = pd.Series([1000.0, 1000.0, 1000.0], index=idx)
    cash = pd.Series([1500.0, -50.0, 0.0], index=idx)     # nonsense inputs are clipped to 0..1 of equity, like invested_share
    adj = BA.cash_credited_equity(eq, cash, RF)
    rf = RF / 100 / D
    assert adj.iloc[1] == pytest.approx(1000.0 * (1 + rf))      # day 1 uses day 0's share: cash 1500 of 1000 equity is clipped to 100% idle
    assert adj.iloc[2] == pytest.approx(adj.iloc[1])            # day 2 uses day 1's share: negative cash is clipped to 0% idle


def test_returns_compose_with_interest_on_the_cash_share():
    idx = _idx(3)
    eq = pd.Series([1000.0, 1100.0, 1100.0], index=idx)
    cash = pd.Series([500.0, 550.0, 550.0], index=idx)     # half in cash at every close
    adj = BA.cash_credited_equity(eq, cash, RF)
    rf = RF / 100 / D
    assert adj.iloc[1] == pytest.approx(1000.0 * (1 + 0.10 + 0.5 * rf))
    assert adj.iloc[2] == pytest.approx(adj.iloc[1] * (1 + 0.0 + 0.5 * rf))


def test_symmetry_all_cash_strategy_has_zero_cash_credited_alpha_and_negative_raw_alpha():
    n = 2 * D + 1
    idx = _idx(n)
    eq = pd.Series(1_000_000.0, index=idx)
    cash = eq.copy()
    nifty = pd.Series(np.linspace(100.0, 160.0, n), index=idx)
    share = BA.invested_share(eq, cash)
    rep = BA.alpha_report(eq, cash, nifty, risk_free_pct=RF, after_tax_rates_pct=(0.0, 20.0))
    assert share.max() == 0.0
    assert rep["cash_credited"]["alpha_pct"] == pytest.approx(0.0, abs=1e-9)
    assert rep["raw"]["alpha_pct"] == pytest.approx(-rep["raw"]["benchmark_cagr_pct"], abs=1e-9) and rep["raw"]["alpha_pct"] < -6.0
    assert rep["gate_alpha_pct"] == rep["cash_credited"]["alpha_pct"]       # the gate uses the cash-credited, pre-tax alpha


def test_alpha_report_after_tax_lines_are_illustrative_and_non_gating():
    n = 3 * D + 1
    idx = _idx(n)
    eq = pd.Series(np.linspace(1_000_000.0, 1_900_000.0, n), index=idx)
    cash = eq * 0.3
    nifty = pd.Series(np.linspace(100.0, 140.0, n), index=idx)
    rep = BA.alpha_report(eq, cash, nifty, risk_free_pct=RF, after_tax_rates_pct=(0.0, 20.0))
    at = rep["after_tax_illustrative"]
    assert set(at) == {"0.0", "20.0"} and at["0.0"]["alpha_pct"] == pytest.approx(rep["cash_credited"]["alpha_pct"])
    assert at["20.0"]["strategy_cagr_pct"] < at["0.0"]["strategy_cagr_pct"] and at["20.0"]["benchmark_cagr_pct"] < at["0.0"]["benchmark_cagr_pct"]
    assert "not tax advice" in rep["after_tax_label"] and "illustrative" in rep["after_tax_label"] and "does not feed back" in rep["note"]
    assert rep["gate_alpha_pct"] == rep["cash_credited"]["alpha_pct"] != at["20.0"]["alpha_pct"]


def test_raw_alpha_equals_the_old_b2_alpha_on_the_same_inputs():
    n = D + 1
    idx = _idx(n)
    eq = pd.Series(np.linspace(1e6, 1.3e6, n), index=idx)
    cash = eq * 0.4
    nifty = pd.Series(np.linspace(100.0, 120.0, n), index=idx)
    share = BA.invested_share(eq, cash)
    bench = BA.benchmark_returns(nifty, share, RF)
    old = BA.alpha_pct(eq, bench)
    rep = BA.alpha_report(eq, cash, nifty, risk_free_pct=RF, after_tax_rates_pct=())
    assert rep["raw"] == old and rep["cash_credited"]["alpha_pct"] > old["alpha_pct"]


def test_implied_annual_return_arithmetic():
    assert BA.implied_annual_return_pct(trades_per_year=30.0, expectancy_r=0.2, max_loss_pct_per_trade=1.0) == pytest.approx(6.0)
    assert BA.implied_annual_return_pct(45.0, 0.15, 1.0) == pytest.approx(6.75)
    assert BA.implied_annual_return_pct(0.0, 0.5, 1.0) == 0.0


def test_module_states_the_after_the_fact_rule():
    doc = BA.cash_credited_equity.__doc__
    assert "after the fact" in doc and "does not feed back" in doc and "sizing" in doc
