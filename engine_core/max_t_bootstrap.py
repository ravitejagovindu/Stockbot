"""
engine_core/max_t_bootstrap.py — Westfall-Young Stepdown Max-T Studentized Block Bootstrap.
========================================================================================
Implements the pre-registered multiple testing procedure for candidate trading strategies.
Controls the Family-Wise Error Rate (FWER <= 0.05) across K correlated configurations
by jointly resampling 4-week non-overlapping blocks and studentizing test statistics.

Pre-registration amendment (Round 2 review): Independent (i.i.d.) weekly resampling
produced an empirical FWER of 2.0% at zero autocorrelation and 18.7% at lag-1 rho = 0.4
(rising to 33% at rho = 0.6).  The strategy's weekly R-sum series exhibits lag-1
autocorrelation of ~0.215-0.237; candidates with more overlapping trades are worse.
The real baseline paired series shows little autocorrelation (lag-1 ~0.08 in W2), but
the strategy side dominates the difference series.

Fix: pre-registered block_size = 4 weeks (approximately one calendar month), which
covers the observed autocorrelation horizon.  Sensitivity runs with block sizes
[2, 4, 8] are also pre-registered.  All resampling is done jointly across K configs
per replication to preserve cross-sectional correlation.

References:
- Westfall, P. H., & Young, S. S. (1993). Resampling-based multiple testing: Examples
  and methods for p-value adjustment. John Wiley & Sons.
- White, H. (2000). A reality check for data snooping. Econometrica, 68(5), 1097-1126.
- Romano, J. P., & Wolf, M. (2005). Stepwise multiple testing as formalized data snooping.
  Econometrica, 73(4), 1237-1282.
- Politis, D. N., & Romano, J. P. (1994). The stationary bootstrap. JASA, 89(428),
  1303-1313.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Union
import numpy as np
import pandas as pd


@dataclass
class BootstrapResult:
    """Results of Westfall-Young Stepdown Max-T Bootstrap."""
    config_id: str
    observed_mean: float
    standard_error: float
    observed_t: float
    unadjusted_p_value: float
    adjusted_p_value: float
    fwer_significant: bool  # adjusted_p_value <= alpha
    confidence_interval_99_lower: float
    confidence_interval_99_upper: float


def assign_calendar_week(d: Union[date, str, pd.Timestamp]) -> str:
    """Return ISO calendar week string YYYY-Www for a given date."""
    if isinstance(d, str):
        d = pd.to_datetime(d).date()
    elif isinstance(d, pd.Timestamp):
        d = d.date()
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def build_weekly_paired_series(
    actual_trades_df: pd.DataFrame,
    random_trades_df: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.Series:
    """Aggregate trade-level net R returns into calendar-week paired net R advantages.

    For each calendar week w:
      actual_r_w: sum of net R of actual trades entered in week w (0.0 if no trades)
      random_r_w: sum of net R of matched random trades entered in week w (0.0 if no trades)
      D_w = actual_r_w - random_r_w

    Test statistic clarification (pre-registered): D_w is the WEEKLY SUM of net-R
    advantage of the strategy over its matched random baseline — NOT per-trade expectancy.
    """
    act = actual_trades_df.copy()
    act["entry_date"] = pd.to_datetime(act["entry_date"]).dt.date
    if start_date:
        act = act[act["entry_date"] >= start_date]
    if end_date:
        act = act[act["entry_date"] <= end_date]

    rnd = random_trades_df.copy()
    rnd["entry_date"] = pd.to_datetime(rnd["entry_date"]).dt.date
    if start_date:
        rnd = rnd[rnd["entry_date"] >= start_date]
    if end_date:
        rnd = rnd[rnd["entry_date"] <= end_date]

    # Map matched trade IDs to their average random net_r
    rnd_trade_means = rnd.groupby(["matched_trade_id", "entry_date"])["net_r"].mean().reset_index()

    act["week"] = act["entry_date"].apply(assign_calendar_week)
    rnd_trade_means["week"] = rnd_trade_means["entry_date"].apply(assign_calendar_week)

    # Get master list of all weeks in period
    all_dates = pd.concat([pd.Series(act["entry_date"]), pd.Series(rnd_trade_means["entry_date"])]).dropna()
    min_date = all_dates.min()
    max_date = all_dates.max()
    full_weeks = sorted(set(pd.date_range(min_date, max_date, freq="W-MON").map(assign_calendar_week)))

    act_wk = act.groupby("week")["net_r"].sum().reindex(full_weeks, fill_value=0.0)
    rnd_wk = rnd_trade_means.groupby("week")["net_r"].sum().reindex(full_weeks, fill_value=0.0)

    return act_wk - rnd_wk


def _block_resample(rng: np.random.Generator, W: int, block_size: int, B: int) -> np.ndarray:
    """Draw B bootstrap samples of length W using non-overlapping block resampling.

    Each bootstrap draw samples ceil(W / block_size) non-overlapping block start indices
    uniformly from {0, block_size, 2*block_size, ...} with replacement, concatenates
    the blocks, clips any tail overflow to [0, W-1], then truncates to exactly W weeks.
    The same index matrix is applied jointly across all K configurations per replication,
    preserving cross-sectional correlation and satisfying subset-pivotality.

    Parameters
    ----------
    rng:
        NumPy Generator (seeded externally for reproducibility).
    W:
        Number of observed weeks.
    block_size:
        Number of consecutive weeks per block (pre-registered: 4).
    B:
        Number of bootstrap replications.

    Returns
    -------
    idx : np.ndarray of shape (B, W), dtype int64
        Row i contains the week indices for replication i.
    """
    if block_size <= 0:
        raise ValueError(f"block_size must be >= 1, got {block_size}")

    # Non-overlapping block start positions: 0, block_size, 2*block_size, ...
    starts = np.arange(0, W, block_size)
    n_blocks_needed = math.ceil(W / block_size)

    # Sample block start indices uniformly with replacement: shape (B, n_blocks_needed)
    chosen = rng.integers(0, len(starts), size=(B, n_blocks_needed))  # indices into starts[]

    # Expand each chosen start into a block of `block_size` consecutive indices.
    # chosen_starts shape: (B, n_blocks_needed)
    chosen_starts = starts[chosen]
    # offsets shape: (block_size,)
    offsets = np.arange(block_size)
    # Broadcasting: (B, n_blocks_needed, block_size)
    indices_full = chosen_starts[:, :, np.newaxis] + offsets[np.newaxis, np.newaxis, :]

    # Flatten blocks and clip overflow (tail block may reach W or beyond)
    idx_flat = indices_full.reshape(B, n_blocks_needed * block_size)
    idx_flat = np.clip(idx_flat, 0, W - 1)

    # Truncate to exactly W weeks
    return idx_flat[:, :W]


class WestfallYoungMaxTBootstrap:
    """Westfall-Young Stepdown Max-T Studentized Block Bootstrap.

    Pre-registered configuration (locked before Step 3):
      - block_size = 4 weeks  (approximately one calendar month)
      - sensitivity_block_sizes = [2, 4, 8]
      - num_replications = 10,000
      - fwer_alpha = 0.05
      - test_statistic = weekly sum of net-R advantage (not per-trade expectancy)

    Rationale for block bootstrap: the strategy's weekly R-sum series exhibits
    lag-1 autocorrelation of ~0.215-0.237; i.i.d. weekly resampling produced FWER
    of only 2.0% at zero autocorrelation and 18.7% at rho=0.4, violating the 5%
    nominal target.  Four-week blocks cover the observed autocorrelation horizon
    while retaining sufficient blocks (~25+) for stable resampling.

    The joint block draw is applied across all K configurations simultaneously
    per replication, preserving cross-sectional correlation and satisfying the
    subset-pivotality condition required for Westfall-Young stepdown validity.
    """

    def __init__(
        self,
        weekly_diffs: pd.DataFrame,
        num_replications: int = 10000,
        fwer_alpha: float = 0.05,
        seed: Optional[int] = 42,
        block_size: int = 4,
        sensitivity_block_sizes: Optional[List[int]] = None,
    ):
        """
        Parameters
        ----------
        weekly_diffs:
            DataFrame where index is calendar week (or time block) and columns
            are configuration IDs (e.g. CFG-01, ..., CFG-06). Each cell contains
            the paired weekly advantage D_{k, w}  (weekly sum of net-R advantage
            of strategy over matched random — NOT per-trade expectancy).
        num_replications:
            Number of bootstrap draws B (default: 10,000).
        fwer_alpha:
            Target Family-Wise Error Rate (default: 0.05).
        seed:
            Random seed for reproducibility.
        block_size:
            Number of consecutive weeks per resampling block (pre-registered: 4).
            Must be >= 1.
        sensitivity_block_sizes:
            Additional block sizes for sensitivity analysis (pre-registered: [2, 4, 8]).
            Sensitivity runs are triggered via run_sensitivity().
        """
        self.data = weekly_diffs.dropna(how="all").fillna(0.0)
        self.B = int(num_replications)
        self.alpha = float(fwer_alpha)
        self.seed = seed
        self.block_size = int(block_size)
        self.sensitivity_block_sizes = (
            sensitivity_block_sizes if sensitivity_block_sizes is not None else [2, 4, 8]
        )
        self.configs = list(self.data.columns)
        self.K = len(self.configs)
        self.W = len(self.data)

        if self.K < 1:
            raise ValueError("weekly_diffs must contain at least 1 column")
        if self.W < 10:
            raise ValueError(f"weekly_diffs must contain at least 10 weeks, got {self.W}")
        if self.block_size < 1:
            raise ValueError(f"block_size must be >= 1, got {self.block_size}")

    def _run_with_block_size(self, block_size: int, rng: np.random.Generator) -> List[BootstrapResult]:
        """Core bootstrap logic parameterised by block_size (internal helper)."""
        X = self.data.values.astype(np.float64)
        W, K = X.shape

        # 1. Observed sample statistics
        obs_mean = np.mean(X, axis=0)   # shape (K,)
        obs_var = np.var(X, axis=0, ddof=1)
        obs_se = np.sqrt(obs_var / W)
        obs_se = np.where(obs_se > 1e-12, obs_se, 1e-12)
        obs_t = obs_mean / obs_se       # studentized observed t-statistic

        # Rank configs by observed t descending: r_1, r_2, ..., r_K
        sort_order = np.argsort(-obs_t)
        t_sorted = obs_t[sort_order]

        # 2. Block-resample calendar weeks (joint draw across all K configs)
        # Center X under H0: X_h0 = X - obs_mean  (null-centering)
        X_h0 = X - obs_mean

        # Block bootstrap index matrix: shape (B, W)
        idx = _block_resample(rng, W, block_size, self.B)

        X_b = X_h0[idx, :]              # shape (B, W, K)
        mean_b = np.mean(X_b, axis=1)  # shape (B, K)
        var_b = np.var(X_b, axis=1, ddof=1)
        se_b = np.sqrt(var_b / W)
        se_b = np.where(se_b > 1e-12, se_b, 1e-12)
        T_boot = mean_b / se_b          # shape (B, K)

        # Unadjusted one-sided p-values: P(T_boot_k >= obs_t_k)
        unadj_p = np.mean(T_boot >= obs_t, axis=0)

        # 3. Westfall-Young Stepdown Algorithm
        # T_boot_sorted shape (B, K)
        T_boot_sorted = T_boot[:, sort_order]

        # Successive maxima q_j,b = max_{m = j..K} T_boot_sorted[b, m]
        q_max = np.zeros((self.B, K), dtype=np.float64)
        q_max[:, K - 1] = T_boot_sorted[:, K - 1]
        for j in range(K - 2, -1, -1):
            q_max[:, j] = np.maximum(q_max[:, j + 1], T_boot_sorted[:, j])

        # Raw stepdown p-values: P(q_max_j >= t_sorted_j)
        p_stepdown_raw = np.mean(q_max >= t_sorted, axis=0)

        # Enforce monotonicity: p_tilde_j = max(p_tilde_{j-1}, p_stepdown_raw_j)
        p_adjusted_sorted = np.zeros(K, dtype=np.float64)
        p_adjusted_sorted[0] = p_stepdown_raw[0]
        for j in range(1, K):
            p_adjusted_sorted[j] = max(p_adjusted_sorted[j - 1], p_stepdown_raw[j])

        # Cap at 1.0
        p_adjusted_sorted = np.minimum(p_adjusted_sorted, 1.0)

        # 4. 99% bootstrap confidence interval of the mean for each config
        ci_idx = rng.integers(0, W, size=(2000, W))
        ci_means = np.mean(X[ci_idx, :], axis=1)   # shape (2000, K)
        ci_99_lower = np.percentile(ci_means, 0.5, axis=0)
        ci_99_upper = np.percentile(ci_means, 99.5, axis=0)

        # Re-map results back to original config ordering
        results_by_cfg: Dict[str, BootstrapResult] = {}
        for rank_idx, orig_idx in enumerate(sort_order):
            cfg_name = self.configs[orig_idx]
            adj_p = float(p_adjusted_sorted[rank_idx])
            results_by_cfg[cfg_name] = BootstrapResult(
                config_id=cfg_name,
                observed_mean=float(obs_mean[orig_idx]),
                standard_error=float(obs_se[orig_idx]),
                observed_t=float(obs_t[orig_idx]),
                unadjusted_p_value=float(unadj_p[orig_idx]),
                adjusted_p_value=adj_p,
                fwer_significant=bool(adj_p <= self.alpha),
                confidence_interval_99_lower=float(ci_99_lower[orig_idx]),
                confidence_interval_99_upper=float(ci_99_upper[orig_idx]),
            )

        return [results_by_cfg[cfg] for cfg in self.configs]

    def run(self) -> List[BootstrapResult]:
        """Execute the pre-registered 4-week block bootstrap and return results."""
        rng = np.random.default_rng(self.seed)
        return self._run_with_block_size(self.block_size, rng)

    def run_sensitivity(self) -> Dict[int, List[BootstrapResult]]:
        """Run sensitivity analysis across pre-registered block sizes [2, 4, 8].

        Returns a dict mapping block_size -> list of BootstrapResult.
        Results should be qualitatively consistent; large divergences indicate
        conclusions are sensitive to the block-length assumption and warrant caution.
        """
        sensitivity_results: Dict[int, List[BootstrapResult]] = {}
        for bs in self.sensitivity_block_sizes:
            rng = np.random.default_rng(self.seed)
            sensitivity_results[bs] = self._run_with_block_size(bs, rng)
        return sensitivity_results
