"""
tests/unit/test_max_t_bootstrap.py — Validation of Westfall-Young Max-T Block Bootstrap.
========================================================================================
Validates that:
1. Under pure noise (H0 true for all 6 configs), the empirical false-positive rate
   (FWER) is approximately 5% (alpha = 0.05) with 4-week block bootstrap.
2. Stepdown adjusted p-values strictly satisfy monotonicity: p_tilde_(1) <= p_tilde_(2) <= ... <= p_tilde_(K).
3. A genuine positive edge is reliably detected with FWER significance.
4. Calendar week assignment correctly formats ISO calendar blocks.
5. Block bootstrap maintains FWER near 5% even with AR(1) autocorrelation (rho = 0.4).
6. Sensitivity analysis results are stable across pre-registered block sizes [2, 4, 8].
"""
from datetime import date
import numpy as np
import pandas as pd
import pytest

from engine_core.max_t_bootstrap import (
    WestfallYoungMaxTBootstrap,
    assign_calendar_week,
    build_weekly_paired_series,
    _block_resample,
)


def test_assign_calendar_week():
    """Verify ISO calendar week assignment."""
    assert assign_calendar_week(date(2020, 1, 1)) == "2020-W01"
    assert assign_calendar_week(date(2020, 1, 15)) == "2020-W03"
    assert assign_calendar_week("2024-05-31") == "2024-W22"


def test_block_resample_shape_and_bounds():
    """Block resample output must have correct shape and values in [0, W-1]."""
    rng = np.random.default_rng(42)
    W, block_size, B = 80, 4, 500
    idx = _block_resample(rng, W, block_size, B)
    assert idx.shape == (B, W), f"Expected ({B}, {W}), got {idx.shape}"
    assert idx.min() >= 0
    assert idx.max() <= W - 1


def test_block_resample_different_from_iid():
    """Block resampling should produce a different distribution from i.i.d. sampling."""
    rng = np.random.default_rng(123)
    W, block_size, B = 80, 4, 1000
    idx = _block_resample(rng, W, block_size, B)
    # In block resampling, consecutive columns within a block should come from the
    # same start, so adjacent-column differences should often be exactly 1.
    # (In i.i.d. sampling the probability of a diff of exactly 1 is 1/W ~ 1.25%)
    diffs = np.diff(idx, axis=1)
    proportion_unit_steps = np.mean(diffs == 1)
    # With 4-week blocks, ~75% of column-pairs should be consecutive unit steps
    assert proportion_unit_steps > 0.5, (
        f"Expected >50% consecutive-step pairs in block resample, got {proportion_unit_steps:.2%}"
    )


def test_stepdown_pvalue_monotonicity():
    """Verify that Westfall-Young adjusted p-values are monotonically non-decreasing."""
    np.random.seed(123)
    # Generate 6 series with varying means
    X = np.random.randn(60, 6)
    X[:, 0] += 0.25
    X[:, 1] += 0.15
    df = pd.DataFrame(X, columns=[f"CFG-{i:02d}" for i in range(1, 7)])

    bs = WestfallYoungMaxTBootstrap(df, num_replications=1000, fwer_alpha=0.05, seed=42, block_size=4)
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

    bs = WestfallYoungMaxTBootstrap(df, num_replications=2000, fwer_alpha=0.05, seed=42, block_size=4)
    results = bs.run()
    cfg03 = next(r for r in results if r.config_id == "CFG-03")

    assert cfg03.adjusted_p_value < 0.05, f"Expected CFG-03 adjusted p < 0.05, got {cfg03.adjusted_p_value}"
    assert cfg03.fwer_significant is True
    assert cfg03.confidence_interval_99_lower > 0.0


def test_empirical_fwer_on_pure_noise():
    """Monte Carlo verification: false-positive rate on pure noise is ~5% with 4-week blocks."""
    np.random.seed(42)
    n_trials = 200
    n_weeks = 80
    k_configs = 6
    false_positive_trials = 0

    for _ in range(n_trials):
        # Correlated noise: shared factor (market noise) + idiosyncratic noise
        market_shock = np.random.randn(n_weeks, 1)
        idio_noise = np.random.randn(n_weeks, k_configs)
        pure_noise = 0.70 * market_shock + 0.71 * idio_noise  # Var ~ 1.0

        df_noise = pd.DataFrame(pure_noise, columns=[f"CFG-{i:02d}" for i in range(1, 7)])
        bs = WestfallYoungMaxTBootstrap(
            df_noise, num_replications=400, fwer_alpha=0.05, seed=None, block_size=4
        )
        results = bs.run()

        # FWER breach if ANY of the 6 pure noise configs is declared significant
        if any(r.fwer_significant for r in results):
            false_positive_trials += 1

    empirical_fwer = false_positive_trials / n_trials

    # Under H0 with alpha = 0.05 across 200 trials, 95% binomial acceptance interval is [2.0%, 8.5%]
    assert 0.02 <= empirical_fwer <= 0.085, (
        f"Empirical FWER {empirical_fwer:.3f} ({false_positive_trials}/{n_trials}) "
        f"deviated from target 5% nominal alpha"
    )


def test_empirical_fwer_with_ar1_autocorrelation():
    """Block bootstrap maintains FWER near 5% even with AR(1) autocorrelation rho=0.4.

    Context: the reviewer's empirical test showed i.i.d. weekly resampling produced
    FWER of 18.7% at rho=0.4 (rising to 33% at rho=0.6).  The pre-registered
    4-week block bootstrap should hold FWER within [2%, 12%] at rho=0.4.
    """
    rng_outer = np.random.default_rng(777)
    n_trials = 200
    n_weeks = 80
    k_configs = 6
    rho = 0.4
    false_positive_trials = 0

    for _ in range(n_trials):
        # Generate AR(1) series for each column: x_t = rho * x_{t-1} + eps_t
        # Stationary variance = sigma^2 / (1 - rho^2)
        sigma = np.sqrt(1.0 - rho ** 2)  # marginal variance = 1.0
        X = np.zeros((n_weeks, k_configs))
        eps = rng_outer.standard_normal((n_weeks, k_configs)) * sigma
        X[0, :] = eps[0, :]
        for t in range(1, n_weeks):
            X[t, :] = rho * X[t - 1, :] + eps[t, :]

        df_ar1 = pd.DataFrame(X, columns=[f"CFG-{i:02d}" for i in range(1, k_configs + 1)])
        bs = WestfallYoungMaxTBootstrap(
            df_ar1, num_replications=400, fwer_alpha=0.05, seed=None, block_size=4
        )
        results = bs.run()

        if any(r.fwer_significant for r in results):
            false_positive_trials += 1

    empirical_fwer = false_positive_trials / n_trials

    # Allow wider tolerance [2%, 12%] to account for Monte Carlo variance at 200 trials
    # (i.i.d. weekly resampling would produce ~18.7% here — block bootstrap must do better)
    assert empirical_fwer <= 0.12, (
        f"Empirical FWER with AR(1) rho=0.4 was {empirical_fwer:.3f} ({false_positive_trials}/{n_trials}); "
        f"expected <= 12% with 4-week block bootstrap (i.i.d. resampling would be ~18.7%)"
    )
    assert empirical_fwer >= 0.01, (
        f"Empirical FWER with AR(1) rho=0.4 was {empirical_fwer:.3f}; "
        f"unexpectedly conservative (should be near 5%)"
    )


def test_sensitivity_block_sizes_consistent():
    """Sensitivity runs with block sizes [2, 4, 8] should produce consistent significance decisions."""
    np.random.seed(456)
    # One clear signal config + 5 noise configs
    X = np.random.randn(80, 6) * 0.5
    X[:, 2] += 0.30  # CFG-03 has a genuine edge

    df = pd.DataFrame(X, columns=[f"CFG-{i:02d}" for i in range(1, 7)])
    bs = WestfallYoungMaxTBootstrap(
        df, num_replications=2000, fwer_alpha=0.05, seed=42,
        block_size=4, sensitivity_block_sizes=[2, 4, 8]
    )
    sensitivity = bs.run_sensitivity()

    assert set(sensitivity.keys()) == {2, 4, 8}, "Sensitivity must return results for block sizes [2, 4, 8]"

    # All block sizes should agree on CFG-03 being significant (strong signal)
    for bsize, res in sensitivity.items():
        cfg03 = next(r for r in res if r.config_id == "CFG-03")
        assert cfg03.fwer_significant, (
            f"block_size={bsize}: CFG-03 should be FWER significant (p={cfg03.adjusted_p_value:.4f})"
        )

    # Adjusted p-values across block sizes should be in a reasonable range of each other
    p_vals = [
        next(r for r in sensitivity[bs_] if r.config_id == "CFG-03").adjusted_p_value
        for bs_ in [2, 4, 8]
    ]
    p_range = max(p_vals) - min(p_vals)
    assert p_range < 0.15, (
        f"Sensitivity p-values diverged too much across block sizes: {dict(zip([2,4,8], p_vals))}"
    )
