"""
tests/unit/test_max_t_bootstrap.py — Validation of Westfall-Young Max-T Block Bootstrap.
========================================================================================
Validates that:
1. Under pure noise (H0 true for all 6 configs), the empirical false-positive rate
   (FWER) is approximately 5% (alpha = 0.05).
2. Stepdown adjusted p-values strictly satisfy monotonicity: p_tilde_(1) <= p_tilde_(2) <= ... <= p_tilde_(K).
3. A genuine positive edge is reliably detected with FWER significance.
4. Calendar week assignment correctly formats ISO calendar blocks.
"""
from datetime import date
import numpy as np
import pandas as pd
import pytest

from engine_core.max_t_bootstrap import (
    WestfallYoungMaxTBootstrap,
    assign_calendar_week,
    build_weekly_paired_series,
)


def test_assign_calendar_week():
    """Verify ISO calendar week assignment."""
    assert assign_calendar_week(date(2020, 1, 1)) == "2020-W01"
    assert assign_calendar_week(date(2020, 1, 15)) == "2020-W03"
    assert assign_calendar_week("2024-05-31") == "2024-W22"


def test_stepdown_pvalue_monotonicity():
    """Verify that Westfall-Young adjusted p-values are monotonically non-decreasing."""
    np.random.seed(123)
    # Generate 6 series with varying means
    X = np.random.randn(60, 6)
    X[:, 0] += 0.25
    X[:, 1] += 0.15
    df = pd.DataFrame(X, columns=[f"CFG-{i:02d}" for i in range(1, 7)])

    bs = WestfallYoungMaxTBootstrap(df, num_replications=1000, fwer_alpha=0.05, seed=42)
    results = bs.run()

    # Sort results by observed_t descending
    sorted_res = sorted(results, key=lambda r: -r.observed_t)
    for i in range(len(sorted_res) - 1):
        assert sorted_res[i].adjusted_p_value <= sorted_res[i + 1].adjusted_p_value + 1e-9, (
            f"Monotonicity violated: {sorted_res[i].config_id} (p={sorted_res[i].adjusted_p_value}) > "
            f"{sorted_res[i+1].config_id} (p={sorted_res[i+1].adjusted_p_value})"
        )


def test_strong_signal_detection():
    """Verify that a true positive signal is detected as FWER significant."""
    np.random.seed(999)
    # 5 pure noise configs + 1 strong positive config (CFG-03 with +0.40R edge)
    noise = np.random.randn(80, 5) * 0.5
    signal = 0.40 + np.random.randn(80, 1) * 0.5

    data = np.hstack([noise[:, :2], signal, noise[:, 2:]])
    df = pd.DataFrame(data, columns=[f"CFG-{i:02d}" for i in range(1, 7)])

    bs = WestfallYoungMaxTBootstrap(df, num_replications=2000, fwer_alpha=0.05, seed=42)
    results = bs.run()
    cfg03 = next(r for r in results if r.config_id == "CFG-03")

    assert cfg03.adjusted_p_value < 0.05, f"Expected CFG-03 adjusted p < 0.05, got {cfg03.adjusted_p_value}"
    assert cfg03.fwer_significant is True
    assert cfg03.confidence_interval_99_lower > 0.0


def test_empirical_fwer_on_pure_noise():
    """Monte Carlo verification: false-positive rate on pure noise across 6 configs is ~5%."""
    np.random.seed(42)
    n_trials = 200
    n_weeks = 80
    k_configs = 6
    false_positive_trials = 0

    for _ in range(n_trials):
        # Correlated noise: shared factor (market noise) + idiosyncratic noise
        market_shock = np.random.randn(n_weeks, 1)
        idio_noise = np.random.randn(n_weeks, k_configs)
        pure_noise = 0.70 * market_shock + 0.71 * idio_noise  # Var = 0.7^2 + 0.71^2 ~ 1.0

        df_noise = pd.DataFrame(pure_noise, columns=[f"CFG-{i:02d}" for i in range(1, 7)])
        bs = WestfallYoungMaxTBootstrap(df_noise, num_replications=400, fwer_alpha=0.05, seed=None)
        results = bs.run()

        # FWER breach if ANY of the 6 pure noise configs is declared significant
        if any(r.fwer_significant for r in results):
            false_positive_trials += 1

    empirical_fwer = false_positive_trials / n_trials

    # Under H0 with alpha = 0.05 across 200 trials, the 95% binomial acceptance interval is [2.0%, 8.5%]
    assert 0.02 <= empirical_fwer <= 0.085, (
        f"Empirical FWER {empirical_fwer:.3f} ({false_positive_trials}/{n_trials}) "
        f"deviated from target 5% nominal alpha"
    )
