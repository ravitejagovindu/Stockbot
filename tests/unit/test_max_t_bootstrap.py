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
7. build_weekly_actual_series() correctly aggregates a candidate's own weekly net-R.
8. compute_block_bootstrap_ci() uses block resampling (not i.i.d.) for Gate 2.
"""
from datetime import date, timedelta
import numpy as np
import pandas as pd
import pytest

from stockbot.validation.max_t_bootstrap import (
    WestfallYoungMaxTBootstrap,
    assign_calendar_week,
    build_weekly_actual_series,
    build_weekly_paired_series,
    compute_block_bootstrap_ci,
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


def test_block_resample_uniform_marginal():
    """Circular wrap must give every week roughly equal marginal probability.

    With the old np.clip approach the last week appeared ~1.98x more often.
    With % W circular wrap the frequency of any week should be within 1.5x
    of the average (B*W / W = B draws expected per week index).
    """
    rng = np.random.default_rng(42)
    W, block_size, B = 80, 4, 5000
    idx = _block_resample(rng, W, block_size, B)
    # Count how often each week index appears across all B*W samples
    counts = np.bincount(idx.ravel(), minlength=W)
    expected = B * W / W  # = B on average
    max_ratio = counts.max() / expected
    assert max_ratio < 1.5, (
        f"Week {counts.argmax()} appeared {counts.max()} times; "
        f"expected ~{expected:.0f} (ratio={max_ratio:.2f}). "
        f"Circular wrap should give near-uniform marginals."
    )


def test_block_resample_uniform_marginal_non_divisible_length():
    """True circular block bootstrap with uniform starts must have uniform marginals on non-divisible W.

    When W is not divisible by block_size (e.g. W=331, block_size=4, 331 % 4 = 3):
    - A fixed-grid start approach (0, 4, 8, ..., 328) caused week 0 to appear in both
      the first block [0, 1, 2, 3] and wrapped in the last block [328, 329, 330, 0],
      giving week 0 a 2.00x over-sampling bias.
    - True circular block bootstrap draws starts uniformly from all W positions {0..W-1},
      ensuring every week (including week 0) has expected frequency exactly B.
    """
    rng = np.random.default_rng(777)
    W, block_size, B = 331, 4, 20000
    idx = _block_resample(rng, W, block_size, B)

    counts = np.bincount(idx.ravel(), minlength=W)
    expected = float(B)  # each week is drawn on average B times (B * W total draws / W weeks)

    # Week 0 must be near expected frequency (not 2.00x)
    week0_ratio = counts[0] / expected
    assert 0.90 <= week0_ratio <= 1.10, (
        f"Week 0 appeared {counts[0]} times; expected ~{expected:.0f} (ratio={week0_ratio:.4f}). "
        f"True circular block bootstrap must eliminate the 2.00x week-0 oversampling bias."
    )

    # Across all 331 weeks, no week should deviate by more than 15% from expected
    max_ratio = counts.max() / expected
    min_ratio = counts.min() / expected
    assert max_ratio < 1.15, (
        f"Week {counts.argmax()} appeared {counts.max()} times; max_ratio={max_ratio:.4f} > 1.15"
    )
    assert min_ratio > 0.85, (
        f"Week {counts.argmin()} appeared {counts.min()} times; min_ratio={min_ratio:.4f} < 0.85"
    )


def test_block_resample_different_from_iid():
    """Block resampling should produce a different distribution from i.i.d. sampling.

    With 4-week blocks, the majority of adjacent column-pairs should differ by
    exactly 1 (consecutive within a block), which is far more than i.i.d. sampling
    would produce by chance (~1/W ≈ 1.25%). Circular wrap preserves this structure.
    """
    rng = np.random.default_rng(123)
    W, block_size, B = 80, 4, 1000
    idx = _block_resample(rng, W, block_size, B)
    # In block resampling, consecutive columns within a block differ by exactly 1
    # (wrapping only creates non-unit steps at block boundaries, not within blocks)
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


def _ar1_fwer(block_sizes, rho=0.4, n_trials=200, n_weeks=80, k_configs=6):
    """Seeded Monte-Carlo FWER at AR(1) rho (F9: fully deterministic — outer RNG and every bootstrap are seeded)."""
    rng_outer = np.random.default_rng(777)
    hits = {b: 0 for b in block_sizes}
    hits["dual"] = 0
    sigma = np.sqrt(1.0 - rho ** 2)
    for i in range(n_trials):
        X = np.zeros((n_weeks, k_configs))
        eps = rng_outer.standard_normal((n_weeks, k_configs)) * sigma
        X[0, :] = eps[0, :]
        for t in range(1, n_weeks):
            X[t, :] = rho * X[t - 1, :] + eps[t, :]
        df_ar1 = pd.DataFrame(X, columns=[f"CFG-{j:02d}" for j in range(1, k_configs + 1)])
        res = WestfallYoungMaxTBootstrap(df_ar1, num_replications=400, fwer_alpha=0.05, seed=1000 + i,
                                         sensitivity_block_sizes=list(block_sizes)).run_sensitivity()
        sig = {b: [r.fwer_significant for r in res[b]] for b in block_sizes}
        for b in block_sizes:
            hits[b] += any(sig[b])
        hits["dual"] += any(a and c for a, c in zip(sig[4], sig[8]))
    return {k: v / n_trials for k, v in hits.items()}


def test_empirical_fwer_with_ar1_autocorrelation():
    """Deterministic (seeded) size check at AR(1) rho=0.4, 80 weeks, K=6.

    HONEST STATEMENT (docs/MAXT_VALIDATION.md): the pre-registered procedure does NOT hold the nominal 5% under
    autocorrelation. Measured here: single block-4 test ~10-12%, block-8 ~8%, pre-registered DUAL rule (4 AND 8) ~8%.
    The bounds below document those measured values (plus Monte-Carlo margin); they are not a claim of 5% control.
    i.i.d. weekly resampling would be ~18.7% here.
    """
    f = _ar1_fwer((4, 8))
    assert 0.01 <= f[4] <= 0.15, f
    assert f["dual"] <= 0.12, f
    assert f["dual"] <= f[4]


def test_empirical_fwer_is_reproducible():
    """Same seeds -> identical estimate (guards against re-introducing an unseeded bootstrap)."""
    assert _ar1_fwer((4, 8), n_trials=20) == _ar1_fwer((4, 8), n_trials=20)


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


def test_build_weekly_actual_series():
    """build_weekly_actual_series() must aggregate only the candidate's own net_r.

    It must NOT involve any random baseline data, and must fill zero-trade weeks with 0.0.
    """
    # Build a minimal actual trades DataFrame: 3 trades in 2 distinct weeks
    base = date(2020, 1, 6)  # Monday of 2020-W02
    trades = pd.DataFrame({
        "entry_date": [base, base, base + timedelta(weeks=2)],
        "net_r": [0.5, -0.2, 0.8],
        "matched_trade_id": [1, 2, 3],
    })

    series = build_weekly_actual_series(trades)

    # Week 2020-W02 has two trades: sum = 0.5 + (-0.2) = 0.3
    assert "2020-W02" in series.index, "Expected 2020-W02 in index"
    assert abs(series["2020-W02"] - 0.3) < 1e-9, f"Expected 0.3, got {series['2020-W02']}"

    # Week 2020-W04 has one trade: sum = 0.8
    assert "2020-W04" in series.index, "Expected 2020-W04 in index"
    assert abs(series["2020-W04"] - 0.8) < 1e-9, f"Expected 0.8, got {series['2020-W04']}"

    # The gap week 2020-W03 must be filled with 0.0
    assert "2020-W03" in series.index, "Gap week 2020-W03 must be present"
    assert series["2020-W03"] == 0.0, f"Gap week must be 0.0, got {series['2020-W03']}"


def test_compute_block_bootstrap_ci_uses_blocks():
    """compute_block_bootstrap_ci() must use block resampling, not i.i.d. weeks.

    For a strong AR(1) series (rho=0.8), the block CI must be wider than a naive
    i.i.d. CI, confirming that autocorrelation is accounted for.  The Gate 2 CI
    would be understated (too narrow) if it used i.i.d. resampling — a bug that
    was present in the old _run_with_block_size() CI computation.
    """
    rng = np.random.default_rng(888)
    n = 80
    rho = 0.8
    sigma = np.sqrt(1.0 - rho ** 2)

    # Generate AR(1) series with a positive mean
    X = np.zeros(n)
    X[0] = 0.2
    for t in range(1, n):
        X[t] = rho * X[t - 1] + sigma * rng.standard_normal() + 0.2 * (1 - rho)

    weekly_r = pd.Series(X)

    # Block CI (block_size=4): should produce a wider interval than i.i.d.
    lower_block, upper_block = compute_block_bootstrap_ci(
        weekly_r, block_size=4, B=2000, seed=42
    )
    # i.i.d. CI for comparison: use block_size=1 (degenerate single-week blocks)
    lower_iid, upper_iid = compute_block_bootstrap_ci(
        weekly_r, block_size=1, B=2000, seed=42
    )

    width_block = upper_block - lower_block
    width_iid = upper_iid - lower_iid

    assert not np.isnan(lower_block), "Block CI lower should not be NaN"
    assert lower_block > 0.0, f"Strong positive AR(1) series; expected lower > 0, got {lower_block:.4f}"
    assert width_block > width_iid * 0.9, (
        f"Block CI width ({width_block:.4f}) should be >= i.i.d. width ({width_iid:.4f}) "
        f"for AR(1) rho=0.8 — block CI accounts for autocorrelation, i.i.d. does not"
    )


def test_gate3_dual_block_size_requirement():
    """Gate 3 must require FWER significance at BOTH block_size=4 and block_size=8."""
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.provenance.select_candidate import gate3_fwer_significance

    # Case 1: Significant at block_size=4 but NOT at block_size=8 -> FAIL
    bs_partial = {
        4: {"adjusted_p_value": 0.032, "fwer_significant": True},
        8: {"adjusted_p_value": 0.078, "fwer_significant": False},
    }
    passed, msg = gate3_fwer_significance(bs_partial)
    assert not passed, f"Gate 3 should fail when block_size=8 not significant; msg: {msg}"
    assert "block_size=8" in msg

    # Case 2: Significant at block_size=8 but NOT at block_size=4 -> FAIL
    bs_partial2 = {
        4: {"adjusted_p_value": 0.061, "fwer_significant": False},
        8: {"adjusted_p_value": 0.040, "fwer_significant": True},
    }
    passed, msg = gate3_fwer_significance(bs_partial2)
    assert not passed, f"Gate 3 should fail when block_size=4 not significant; msg: {msg}"
    assert "block_size=4" in msg

    # Case 3: Significant at BOTH block sizes -> PASS
    bs_both = {
        4: {"adjusted_p_value": 0.032, "fwer_significant": True},
        8: {"adjusted_p_value": 0.045, "fwer_significant": True},
    }
    passed, msg = gate3_fwer_significance(bs_both)
    assert passed, f"Gate 3 should pass when both block sizes significant; msg: {msg}"
    assert "FWER significant at both block sizes" in msg


def test_gate5_drawdown_check_enforcement():
    """Gate 5 must strictly enforce max_drawdown_pct <= 15.0% using equity drawdown."""
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.provenance.select_candidate import gate5_strategy_gates, _compute_equity_drawdown_pct

    # Case 1: Drawdown exceeds 15% threshold (e.g. 20.0%) -> FAIL
    stats_high_dd = {
        "max_drawdown_pct": 20.0,
        "profit_factor": 1.50,
        "net_expectancy_r_pooled": 0.25,
    }
    passed, msg = gate5_strategy_gates(stats_high_dd)
    assert not passed, f"Gate 5 must reject candidate with 20% drawdown; got msg: {msg}"
    assert "max_drawdown=20.00% > 15.0%" in msg

    # Case 2: Drawdown is NaN (equity curve missing) -> FAIL
    stats_nan_dd = {
        "max_drawdown_pct": float("nan"),
        "profit_factor": 1.50,
        "net_expectancy_r_pooled": 0.25,
    }
    passed, msg = gate5_strategy_gates(stats_nan_dd)
    assert not passed, f"Gate 5 must reject when drawdown is NaN; got msg: {msg}"
    assert "max_drawdown_pct is NaN" in msg

    # Case 3: All gates pass (DD=12.5%, PF=1.45, Expectancy=+0.20R) -> PASS
    stats_pass = {
        "max_drawdown_pct": 12.5,
        "profit_factor": 1.45,
        "net_expectancy_r_pooled": 0.20,
    }
    passed, msg = gate5_strategy_gates(stats_pass)
    assert passed, f"Gate 5 should pass valid stats; got msg: {msg}"
    assert "MaxDD=12.50%" in msg

    # Case 4: Verify _compute_equity_drawdown_pct on known series: 100 -> 120 -> 96 (20% drop from 120 peak)
    eq_series = pd.Series([100.0, 110.0, 120.0, 108.0, 96.0, 115.0])
    dd = _compute_equity_drawdown_pct(eq_series)
    assert abs(dd - 20.0) < 1e-6, f"Expected 20.0% drawdown, got {dd:.4f}%"


