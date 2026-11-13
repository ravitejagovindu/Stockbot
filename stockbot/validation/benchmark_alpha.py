"""Shared analytics for the B2 benchmark and the alpha gate: matched Nifty benchmark, cash-credited strategy equity, alpha, illustrative after-tax alpha, implied annual return.

One module for every user (scripts/evaluate_validation_gates_near_52w_high.py, scripts/benchmark_nifty_matched_near_52w_high.py, scripts/validate_family.py through the evaluate script).

Cash symmetry. The B2 benchmark credits ``risk_free_pct`` on the share of the Nifty-matched portfolio that is not invested; before this module the strategy's own idle cash earned nothing,
so every strategy was charged the risk-free rate against it. ``cash_credited_equity`` gives the strategy the same credit: each day's idle cash (at the PREVIOUS close) earns
``risk_free_pct / 100 / 252``. The interest is applied AFTER THE FACT, in the analytics layer, on the engine's recorded equity and cash; it does not feed back into sizing, caps or any
other decision, and the engine State is never touched.

Gate rule: the alpha gate uses the cash-credited, PRE-TAX alpha (``alpha_report(...)["gate_alpha_pct"]``). The raw alpha (no credit) is reported beside it. After-tax lines, at the rates in
``reporting.after_tax_rates_pct``, are illustrative only, labelled so, and decide nothing. Both sides are price returns (the lake has no dividends).
"""
from __future__ import annotations

from typing import Optional, Sequence

import pandas as pd

TRADING_DAYS = 252
AFTER_TAX_LABEL = "illustrative, not tax advice: tax charged on the end gain of the cash-credited strategy and of its benchmark; never a gate input"
NOTE = ("Cash credit is applied after the fact on the recorded equity and cash (idle cash at the previous close earns risk_free_pct/100/252 per day); it does not feed back into sizing "
        "or any engine decision. The gate uses the cash-credited, pre-tax alpha.")


def invested_share(equity: pd.Series, cash: pd.Series) -> pd.Series:
    """Share of equity not in cash at each close, clipped to 0..1."""
    return (1.0 - cash / equity).clip(lower=0.0, upper=1.0)


def benchmark_returns(nifty: pd.Series, share: pd.Series, risk_free_pct: float, *, constant_share: bool = False, trading_days: int = TRADING_DAYS) -> pd.Series:
    """Daily benchmark returns from the second common date on; each day uses the share at the PREVIOUS close.
    Daily return = s(t-1) x Nifty close-to-close return + (1 - s(t-1)) x risk_free_pct / 100 / 252."""
    idx = sorted(set(nifty.index) & set(share.index))
    nifty, share = nifty.loc[idx], share.loc[idx]
    if constant_share:
        share = pd.Series(float(share.mean()), index=pd.Index(idx))
    ret = nifty.pct_change().iloc[1:]
    prev = share.shift(1).iloc[1:]
    rf = risk_free_pct / 100.0 / trading_days
    return prev * ret + (1.0 - prev) * rf


def cash_credited_equity(equity: pd.Series, cash: pd.Series, risk_free_pct: float, *, trading_days: int = TRADING_DAYS) -> pd.Series:
    """The strategy's equity with its idle cash credited at the risk-free rate, the mirror of the benchmark's credit on its un-invested share.

    Day t return = (equity(t) / equity(t-1) - 1) + c(t-1) x risk_free_pct / 100 / 252, where c(t-1) = cash(t-1) / equity(t-1) is the idle-cash share at the PREVIOUS close, clipped to 0..1
    (the same clip as ``invested_share``). The adjusted series starts at the first equity value and compounds those returns.
    Interest is applied after the fact, on recorded values only: it does not feed back into sizing, caps or any engine decision, and neither input is modified."""
    eq = equity.astype(float)
    idle = (1.0 - invested_share(eq, cash.reindex(eq.index).ffill().fillna(0.0))).shift(1)
    rf = risk_free_pct / 100.0 / trading_days
    r = eq.pct_change().fillna(0.0) + idle.fillna(0.0) * rf
    return float(eq.iloc[0]) * (1.0 + r).cumprod()


def _after_tax_end(start: float, end: float, tax_pct: float) -> float:
    return start + (end - start) * (1.0 - tax_pct / 100.0) if end > start else end


def alpha_pct(strategy_equity: pd.Series, bench_returns: pd.Series, *, tax_pct: float = 0.0) -> dict:
    """Annualised alpha in percentage points: strategy CAGR minus benchmark CAGR over the strategy's first to last date (365.25-day years), each after tax on a gain."""
    first, last = strategy_equity.index[0], strategy_equity.index[-1]
    years = (last - first).days / 365.25
    s0, s1 = float(strategy_equity.iloc[0]), float(strategy_equity.iloc[-1])
    b0, b1 = 1.0, float((1.0 + bench_returns).prod())
    s1, b1 = _after_tax_end(s0, s1, tax_pct), _after_tax_end(b0, b1, tax_pct)
    cs, cb = 100.0 * ((s1 / s0) ** (1.0 / years) - 1.0), 100.0 * ((b1 / b0) ** (1.0 / years) - 1.0)
    return {"years": years, "strategy_cagr_pct": cs, "benchmark_cagr_pct": cb, "alpha_pct": cs - cb}


def alpha_report(equity: pd.Series, cash: pd.Series, nifty: pd.Series, *, risk_free_pct: float, after_tax_rates_pct: Sequence[float] = (), share: Optional[pd.Series] = None) -> dict:
    """Alpha against the matched benchmark, three ways: ``raw`` (strategy cash earns nothing, as before), ``cash_credited`` (pre-tax; THE GATE VALUE, ``gate_alpha_pct``), and
    ``after_tax_illustrative`` per rate (cash-credited, tax on the end gain; non-gating). The benchmark is matched to ``share`` (the invested share at each close; default: from
    ``equity`` and ``cash``) and restricted to the equity dates. The private ``_credited_equity``, ``_benchmark_returns`` and ``_share`` entries are the series behind the numbers."""
    eq = equity.astype(float)
    cash_on = cash.reindex(eq.index).ffill().fillna(0.0)
    share = invested_share(eq, cash_on) if share is None else share
    bench = benchmark_returns(nifty, share, risk_free_pct)
    on = set(eq.index)
    bench = bench.loc[[d for d in bench.index if d in on]]
    credited = cash_credited_equity(eq, cash_on, risk_free_pct)
    raw = alpha_pct(eq, bench)
    cc = alpha_pct(credited, bench)
    return {"raw": raw, "cash_credited": cc, "gate_alpha_pct": cc["alpha_pct"], "after_tax_label": AFTER_TAX_LABEL, "note": NOTE, "risk_free_pct": risk_free_pct,
            "after_tax_illustrative": {str(float(t)): alpha_pct(credited, bench, tax_pct=float(t)) for t in after_tax_rates_pct},
            "_credited_equity": credited, "_benchmark_returns": bench, "_share": share}


def implied_annual_return_pct(trades_per_year: float, expectancy_r: float, max_loss_pct_per_trade: float) -> float:
    """Reported, non-gating: trades per year x expectancy (net R per trade) x the shared max loss per trade (% of equity) = the annual return the expectancy would imply
    if every trade risked exactly the maximum and the gains simply added up."""
    return float(trades_per_year) * float(expectancy_r) * float(max_loss_pct_per_trade)
