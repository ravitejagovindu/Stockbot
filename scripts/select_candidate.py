"""
scripts/select_candidate.py — Automated Pre-Registered Candidate Selection.
============================================================================
Applies all pre-registered gates from backtest/pre_registered_configs.yaml in sequence.
Writes a committed JSON decision file and an append-only CSV trial ledger to eliminate
discretion from the selection process.

Gate sequence (must match pre_registered_configs.yaml selection_automation.gate_sequence):
  Gate 1: Trade volume floors (pooled >= 80, W1 >= 20, W2 >= 20)
  Gate 2: 99% BLOCK-bootstrap CI lower bound of candidate's own absolute weekly net-R > 0.0R
           (block_size=4, circular wrap — uses compute_block_bootstrap_ci() on actual trades only,
           NOT the paired-advantage CI from the Max-T output)
  Gate 3: Max-T FWER-adjusted p-value <= 0.05 at BOTH block_size=4 AND block_size=8
  Gate 4: Plateau check — every neighbor in adjacency graph has expectancy >= 75% of winner AND > 0.0R
           (applied to the single highest-expectancy finalist only; no fallback if it fails)
  Gate 5: Official strategy gates (max DD <= 15% of equity, PF >= 1.30, net expectancy >= +0.15R)

Outputs (both must be committed):
  backtest/outputs/selection_decision.json   — decision with gate results per config
  backtest/outputs/trial_ledger.csv          — append-only audit log of each run

Usage:
  py -3 scripts/select_candidate.py [--dry-run]

  --dry-run : Print results without writing outputs.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUTS_DIR = PROJECT_ROOT / "backtest" / "outputs"
DECISION_FILE = OUTPUTS_DIR / "selection_decision.json"
TRIAL_LEDGER = OUTPUTS_DIR / "trial_ledger.csv"
PRE_REG_YAML = PROJECT_ROOT / "stockbot" / "validation" / "ledger" / "records" / "pre_registered_configs.yaml"

# Pre-registered adjacency graph (must match pre_registered_configs.yaml)
ADJACENCY_GRAPH: Dict[str, List[str]] = {
    "CFG-01": ["CFG-02", "CFG-04"],
    "CFG-02": ["CFG-01", "CFG-03", "CFG-05"],
    "CFG-03": ["CFG-02", "CFG-06"],
    "CFG-04": ["CFG-01", "CFG-05"],
    "CFG-05": ["CFG-04", "CFG-06", "CFG-02"],
    "CFG-06": ["CFG-05", "CFG-03"],
}

# Pre-registered gate thresholds
GATE_MIN_POOLED_TRADES = 80
GATE_MIN_TRADES_PER_WINDOW = 20
GATE_CI_LOWER_BOUND_GT = 0.0          # Gate 2: absolute net-R CI lower bound must exceed this
GATE_FWER_ALPHA = 0.05                 # Gate 3: FWER threshold
GATE_FWER_BLOCK_SIZES = [4, 8]        # Gate 3: must be significant at BOTH block sizes
GATE_PLATEAU_RATIO = 0.75             # Gate 4: neighbor must be >= 75% of winner's expectancy
GATE_MAX_DD_PCT = 15.0                 # Gate 5: max drawdown as % of equity
GATE_MIN_PF = 1.30                     # Gate 5: profit factor
GATE_MIN_EXPECTANCY_R = 0.15          # Gate 5: net expectancy in R

BOOTSTRAP_REPLICATIONS = 10000

# F6: the registry ledger (hash-chained, committed) is always stockbot/validation/ledger/records/trial_ledger.csv (moved from backtest/outputs in Phase 7), even when a
# diagnostic run reads/writes another outputs folder. Dry runs / alternate folders are logged in the exploratory log.
REGISTRY_LEDGER = PROJECT_ROOT / "stockbot" / "validation" / "ledger" / "records" / "trial_ledger.csv"
EXPLORATORY_LOG = PROJECT_ROOT / "stockbot" / "validation" / "ledger" / "records" / "trial_ledger_exploratory.csv"


def gate_parameters() -> Dict[str, Any]:
    """The pre-registered selection-gate parameters; their hash is stored in the REGISTRATION ledger row."""
    return {
        "min_pooled_trades": GATE_MIN_POOLED_TRADES, "min_trades_per_window": GATE_MIN_TRADES_PER_WINDOW,
        "ci_lower_bound_gt": GATE_CI_LOWER_BOUND_GT, "fwer_alpha": GATE_FWER_ALPHA,
        "fwer_block_sizes": GATE_FWER_BLOCK_SIZES, "plateau_ratio": GATE_PLATEAU_RATIO,
        "max_dd_pct": GATE_MAX_DD_PCT, "min_pf": GATE_MIN_PF, "min_expectancy_r": GATE_MIN_EXPECTANCY_R,
        "bootstrap_replications": BOOTSTRAP_REPLICATIONS, "bootstrap_block_size": BOOTSTRAP_BLOCK_SIZE,
        "adjacency_graph": ADJACENCY_GRAPH, "r_column": "net_r",
    }


def _candidate_count() -> int:
    return len([c for c in _load_yaml(PRE_REG_YAML).get("configs", []) if c.get("role") == "CANDIDATE"])


def register(reason: str | None = None) -> None:
    """Write the REGISTRATION row (YAML hash, gate hash, config budget). Re-registration needs an explicit reason. The writer lives in stockbot.validation.ledger (Phase 7)."""
    from stockbot.validation import ledger

    cids = [c["id"] for c in _load_yaml(PRE_REG_YAML).get("configs", []) if c.get("role") == "CANDIDATE"]
    rec = ledger.register(ledger=REGISTRY_LEDGER, yaml_path=PRE_REG_YAML, gate_params=gate_parameters(), candidate_ids=cids, git_sha=_git_head_sha(), reason=reason)
    print(f"Registered: yaml={rec['yaml_sha256'][:12]} gates={rec['gates_sha256'][:12]} budget={rec['budget']}")


def _log_exploratory(note: str, selected, gate_reached: dict) -> None:
    """Dry-run / diagnostic-folder runs are still counted (F6). The writer lives in stockbot.validation.ledger (Phase 7)."""
    from stockbot.validation import ledger

    ledger.record_exploratory(path=EXPLORATORY_LOG, note=note, selected=selected, gate_reached=gate_reached, git_sha=_git_head_sha(), source=str(OUTPUTS_DIR))


BOOTSTRAP_BLOCK_SIZE = 4              # Primary block size (Gate 3 also checks block_size=8)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _git_head_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()[:12] if result.returncode == 0 else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


R_COL = "net_r"          # explicit R column used by every gate (F1)
GROSS_R_COL = "gross_r"  # must also be present so gross-vs-net mix-ups are detectable


def require_r_columns(df: pd.DataFrame) -> None:
    """Fail loudly unless explicit, distinct gross/net R columns are present (F1).

    Raises ValueError if ``net_r`` or ``gross_r`` is missing (legacy CSVs carried an orphan ``net_r`` that
    equalled the gross price-based R), or if ``net_r`` is identical to ``gross_r`` on rows with non-zero costs.
    """
    for col in (R_COL, GROSS_R_COL):
        if col not in df.columns:
            raise ValueError(
                f"Trade file lacks explicit column '{col}'. Legacy files with an unexplained 'net_r' are refused; "
                "regenerate with the Simulator or scripts/recompute_step3_net_r.py."
            )
    if "costs" in df.columns:
        paid = df[df["costs"] > 0]
        if len(paid) and np.allclose(paid[R_COL].values, paid[GROSS_R_COL].values, rtol=0, atol=1e-12):
            raise ValueError("net_r is identical to gross_r on rows with non-zero costs: net R is not net of costs.")


def configure_outputs(outputs_dir: Path) -> None:
    """Point all input/output paths at ``outputs_dir`` (used for recomputed/alternate result folders)."""
    global OUTPUTS_DIR, DECISION_FILE, TRIAL_LEDGER
    OUTPUTS_DIR = Path(outputs_dir)
    DECISION_FILE = OUTPUTS_DIR / "selection_decision.json"
    TRIAL_LEDGER = OUTPUTS_DIR / "trial_ledger.csv"


def _load_trades(config_id: str) -> Optional[pd.DataFrame]:
    """Load trade CSV for a candidate config. Returns None if file missing."""
    for filename in (
        f"trades_candidate_{config_id}.csv",
        f"trades_{config_id}_pooled.csv",
    ):
        path = OUTPUTS_DIR / filename
        if path.exists():
            df = pd.read_csv(path)
            require_r_columns(df)
            if "excluded_ca" in df.columns:  # F3: trades touched by unhandled corporate actions leave the statistics
                n_ex = int(df["excluded_ca"].astype(bool).sum())
                if n_ex:
                    print(f"  [F3] {config_id}: excluding {n_ex} trade(s) flagged excluded_ca")
                df = df[~df["excluded_ca"].astype(bool)].reset_index(drop=True)
            return df
    return None


def _load_random_baseline(config_id: str) -> Optional[pd.DataFrame]:
    """Load matched random baseline CSV for a candidate config."""
    for filename in (
        f"apples_to_apples_random_trades_{config_id}.csv",
        "apples_to_apples_random_trades.csv",
    ):
        path = OUTPUTS_DIR / filename
        if path.exists():
            return pd.read_csv(path)
    return None


def _load_equity(config_id: str, window: str) -> Optional[pd.Series]:
    """Load daily equity series for a config and window from backtest outputs."""
    window_suffixes = {
        "W1": ["window_2020_2021", "2020_2021", "W1", "w1"],
        "W2": ["window_2022_2026", "2022_2026", "W2", "w2"],
    }
    suffixes = window_suffixes.get(window, [window])
    for sfx in suffixes:
        for fname in (
            f"equity_{config_id}_{sfx}.csv",
            f"equity_candidate_{config_id}_{sfx}.csv",
        ):
            p = OUTPUTS_DIR / fname
            if p.exists():
                try:
                    df = pd.read_csv(p, index_col=0)
                    return df.iloc[:, 0].dropna()
                except Exception:
                    continue
    return None


def _compute_equity_drawdown_pct(equity: Optional[pd.Series]) -> float:
    """Compute maximum peak-to-trough percentage drawdown from daily equity series."""
    if equity is None or len(equity) < 2:
        return float("nan")
    s = pd.to_numeric(equity, errors="coerce").dropna()
    if len(s) < 2:
        return float("nan")
    cummax = s.cummax()
    valid = cummax > 0
    if not valid.any():
        return float("nan")
    dd = (cummax[valid] - s[valid]) / cummax[valid] * 100.0
    return float(dd.max()) if len(dd) else 0.0


def _compute_gate2_ci(trades_df: pd.DataFrame) -> Tuple[float, float]:
    """Gate 2: compute 99% block-bootstrap CI on the candidate's own absolute weekly net-R.

    Uses build_weekly_actual_series() (actual trades only, no random baseline) and
    compute_block_bootstrap_ci() (circular block_size=4, B=2000).

    This is the PRE-REGISTERED Gate 2 quantity — NOT the paired-advantage CI that
    comes out of the Max-T bootstrap (which is on D_{k,w} = actual - random).
    Gate 2 and Gate 3 test different hypotheses:
      Gate 2: Is the strategy profitable in absolute terms?  (lower CI of own net-R > 0)
      Gate 3: Does it beat a matched random baseline?        (Max-T FWER p-value <= 0.05)
    """
    from stockbot.validation.max_t_bootstrap import (
        build_weekly_actual_series,
        compute_block_bootstrap_ci,
    )
    try:
        weekly_r = build_weekly_actual_series(trades_df)
        if weekly_r.empty or len(weekly_r) < 4:
            return (float("nan"), float("nan"))
        return compute_block_bootstrap_ci(
            weekly_r,
            block_size=BOOTSTRAP_BLOCK_SIZE,
            B=2000,
            alpha_ci=0.01,   # 99% CI
            seed=42,
        )
    except Exception as exc:
        print(f"  [WARN] Gate 2 CI computation failed: {exc}")
        return (float("nan"), float("nan"))


def _compute_trade_stats(trades_df: pd.DataFrame, config_id: Optional[str] = None) -> Dict[str, Any]:
    """Compute per-window and pooled trade statistics, including simulator equity drawdown."""
    stats: Dict[str, Any] = {}
    for col in ("window", "net_r"):
        if col not in trades_df.columns:
            return {"error": f"Missing column: {col}"}

    for window_label in ("W1", "W2"):
        wdf = trades_df[trades_df["window"].astype(str).str.startswith(window_label)]
        stats[f"trades_{window_label}"] = len(wdf)
        stats[f"net_expectancy_r_{window_label}"] = (
            float(wdf["net_r"].mean()) if len(wdf) else float("nan")
        )
        if config_id:
            eq = _load_equity(config_id, window_label)
            stats[f"max_drawdown_pct_{window_label}"] = _compute_equity_drawdown_pct(eq)
        else:
            stats[f"max_drawdown_pct_{window_label}"] = float("nan")

    stats["trades_pooled"] = len(trades_df)
    stats["net_expectancy_r_pooled"] = (
        float(trades_df["net_r"].mean()) if len(trades_df) else float("nan")
    )
    stats["profit_factor"] = _profit_factor(trades_df["net_r"])

    # Determine window-level equity max drawdown percentage from the simulator
    w1_dd = stats.get("max_drawdown_pct_W1", float("nan"))
    w2_dd = stats.get("max_drawdown_pct_W2", float("nan"))
    if not np.isnan(w1_dd) and not np.isnan(w2_dd):
        stats["max_drawdown_pct"] = max(w1_dd, w2_dd)
    elif not np.isnan(w1_dd):
        stats["max_drawdown_pct"] = w1_dd
    elif not np.isnan(w2_dd):
        stats["max_drawdown_pct"] = w2_dd
    else:
        # Fallback if equity curves are not yet generated: compute approximate drawdown from trade P&L if available
        if "pnl_net" in trades_df.columns and len(trades_df):
            eq_curve = 1_000_000.0 + trades_df["pnl_net"].cumsum()
            cm = eq_curve.cummax()
            valid = cm > 0
            stats["max_drawdown_pct"] = (
                float(((cm[valid] - eq_curve[valid]) / cm[valid]).max() * 100.0)
                if valid.any() else float("nan")
            )
        else:
            stats["max_drawdown_pct"] = float("nan")

    # Trade R-based drawdown for reference
    eq_r = trades_df["net_r"].cumsum()
    running_max_r = eq_r.cummax()
    dd_r = eq_r - running_max_r
    stats["max_drawdown_r"] = float(dd_r.min()) if len(dd_r) else float("nan")
    stats["max_drawdown_r_abs"] = float(abs(dd_r.min())) if len(dd_r) else float("nan")

    return stats


def _profit_factor(net_r: pd.Series) -> float:
    gross_win = net_r[net_r > 0].sum()
    gross_loss = abs(net_r[net_r < 0].sum())
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 1.0
    return float(gross_win / gross_loss)


def _bootstrap_ci_and_maxt(
    candidates: Dict[str, Tuple[pd.DataFrame, pd.DataFrame]],
) -> Dict[str, Dict[int, Any]]:
    """Run block bootstrap for all candidates jointly at all pre-registered block sizes.

    Parameters
    ----------
    candidates:
        Dict of config_id -> (actual_trades_df, random_trades_df).

    Returns
    -------
    Dict mapping config_id to dict of block_size -> bootstrap result dict.
    """
    from stockbot.validation.max_t_bootstrap import (
        WestfallYoungMaxTBootstrap,
        build_weekly_paired_series,
        BootstrapResult,
    )

    weekly_cols: Dict[str, pd.Series] = {}
    for cfg_id, (actual_df, random_df) in candidates.items():
        try:
            series = build_weekly_paired_series(actual_df, random_df)
            weekly_cols[cfg_id] = series
        except Exception as exc:
            print(f"  [WARN] Failed to build weekly series for {cfg_id}: {exc}")

    if not weekly_cols:
        return {}

    # Align all series on the union of weeks
    weekly_df = pd.DataFrame(weekly_cols).fillna(0.0)

    if len(weekly_df) < 10:
        print(f"  [WARN] Only {len(weekly_df)} weeks available; bootstrap may be unreliable")

    bs = WestfallYoungMaxTBootstrap(
        weekly_df,
        num_replications=BOOTSTRAP_REPLICATIONS,
        fwer_alpha=GATE_FWER_ALPHA,
        seed=42,
        block_size=BOOTSTRAP_BLOCK_SIZE,
        sensitivity_block_sizes=GATE_FWER_BLOCK_SIZES,
    )
    sensitivity_results: Dict[int, List[BootstrapResult]] = bs.run_sensitivity()

    output: Dict[str, Dict[int, Any]] = {cfg_id: {} for cfg_id in weekly_cols}
    for bsize, results_list in sensitivity_results.items():
        for r in results_list:
            output[r.config_id][bsize] = {
                "observed_mean": r.observed_mean,
                "standard_error": r.standard_error,
                "observed_t": r.observed_t,
                "unadjusted_p_value": r.unadjusted_p_value,
                "adjusted_p_value": r.adjusted_p_value,
                "fwer_significant": r.fwer_significant,
                "ci_99_lower_paired": r.confidence_interval_99_lower,
                "ci_99_upper_paired": r.confidence_interval_99_upper,
            }

    return output


# ---------------------------------------------------------------------------
# Gate evaluators
# ---------------------------------------------------------------------------

def gate1_volume_floors(stats: Dict[str, Any]) -> Tuple[bool, str]:
    """Gate 1: Trade volume floors."""
    if "error" in stats:
        return False, f"Trade stats error: {stats['error']}"
    pooled = stats.get("trades_pooled", 0)
    w1 = stats.get("trades_W1", 0)
    w2 = stats.get("trades_W2", 0)
    reasons = []
    if pooled < GATE_MIN_POOLED_TRADES:
        reasons.append(f"pooled_trades={pooled} < {GATE_MIN_POOLED_TRADES}")
    if w1 < GATE_MIN_TRADES_PER_WINDOW:
        reasons.append(f"trades_W1={w1} < {GATE_MIN_TRADES_PER_WINDOW}")
    if w2 < GATE_MIN_TRADES_PER_WINDOW:
        reasons.append(f"trades_W2={w2} < {GATE_MIN_TRADES_PER_WINDOW}")
    if reasons:
        return False, "; ".join(reasons)
    return True, f"pooled={pooled}, W1={w1}, W2={w2}"


def gate2_ci_lower_bound(ci: Tuple[float, float]) -> Tuple[bool, str]:
    """Gate 2: 99% block-bootstrap CI lower bound of candidate's absolute net-R > 0.0R.

    The CI is computed by _compute_gate2_ci() using the candidate's OWN actual weekly
    net-R (not the paired advantage over random — that is Gate 3's domain).
    """
    lower, upper = ci
    if np.isnan(lower):
        return False, "Block-bootstrap CI unavailable (insufficient data or computation error)"
    if lower <= GATE_CI_LOWER_BOUND_GT:
        return False, f"99% block CI lower bound {lower:.4f}R <= 0.0R (absolute net-R not reliably positive)"
    return True, f"99% block CI lower bound {lower:.4f}R > 0.0R (absolute weekly net-R reliably positive)"


def gate3_fwer_significance(bs_by_block: Dict[int, Any]) -> Tuple[bool, str]:
    """Gate 3: Max-T FWER-adjusted p-value <= 0.05 at BOTH block_size=4 AND block_size=8 (pre-registered)."""
    if not bs_by_block:
        return False, "Bootstrap result unavailable"
    failures = []
    details = []
    for bsize in GATE_FWER_BLOCK_SIZES:
        result = bs_by_block.get(bsize, {})
        if not result:
            failures.append(f"block_size={bsize}: no result")
            continue
        adj_p = result.get("adjusted_p_value", float("nan"))
        sig = result.get("fwer_significant", False)
        details.append(f"bs{bsize}: adj_p={adj_p:.4f}")
        if np.isnan(adj_p) or not sig:
            failures.append(f"block_size={bsize}: adj_p={adj_p:.4f} > {GATE_FWER_ALPHA}")
    if failures:
        return False, "Not FWER significant at all required block sizes: " + "; ".join(failures)
    return True, f"FWER significant at both block sizes [{', '.join(details)}]"


def gate4_plateau(winner_id: str, all_stats: Dict[str, Dict[str, Any]]) -> Tuple[bool, str]:
    """Gate 4: Every neighbor in adjacency graph meets plateau criterion."""
    winner_exp = all_stats.get(winner_id, {}).get("net_expectancy_r_pooled", float("nan"))
    if np.isnan(winner_exp) or winner_exp <= 0:
        return False, f"Winner expectancy {winner_exp:.4f}R is non-positive"

    neighbors = ADJACENCY_GRAPH.get(winner_id, [])
    if not neighbors:
        return True, "No neighbors defined in adjacency graph"

    failures = []
    for nbr_id in neighbors:
        nbr_stats = all_stats.get(nbr_id)
        if nbr_stats is None:
            failures.append(f"{nbr_id}: no data")
            continue
        nbr_exp = nbr_stats.get("net_expectancy_r_pooled", float("nan"))
        threshold = GATE_PLATEAU_RATIO * winner_exp
        if np.isnan(nbr_exp):
            failures.append(f"{nbr_id}: expectancy NaN")
        elif nbr_exp <= 0:
            failures.append(f"{nbr_id}: expectancy {nbr_exp:.4f}R <= 0.0R")
        elif nbr_exp < threshold:
            failures.append(
                f"{nbr_id}: expectancy {nbr_exp:.4f}R < {threshold:.4f}R "
                f"(75% of winner {winner_exp:.4f}R)"
            )
    if failures:
        return False, "Plateau violated: " + "; ".join(failures)
    return True, f"All {len(neighbors)} neighbors pass plateau ({GATE_PLATEAU_RATIO:.0%} of {winner_exp:.4f}R)"


def gate5_strategy_gates(stats: Dict[str, Any]) -> Tuple[bool, str]:
    """Gate 5: Official strategy gates (Max DD <= 15.0%, PF >= 1.30, Expectancy >= +0.15R)."""
    reasons = []
    max_dd_pct = stats.get("max_drawdown_pct", float("nan"))
    pf = stats.get("profit_factor", float("nan"))
    exp = stats.get("net_expectancy_r_pooled", float("nan"))

    # Gate 5.1: Maximum equity-curve drawdown <= 15.0% (per-window from simulator)
    if np.isnan(max_dd_pct):
        reasons.append("max_drawdown_pct is NaN (equity curve unavailable)")
    elif max_dd_pct > GATE_MAX_DD_PCT:
        reasons.append(f"max_drawdown={max_dd_pct:.2f}% > {GATE_MAX_DD_PCT}%")

    # Gate 5.2: Profit factor >= 1.30
    if np.isnan(pf) or pf < GATE_MIN_PF:
        reasons.append(f"profit_factor={pf:.3f} < {GATE_MIN_PF}")

    # Gate 5.3: Net expectancy >= +0.15R
    if np.isnan(exp) or exp < GATE_MIN_EXPECTANCY_R:
        reasons.append(f"net_expectancy_r={exp:.4f}R < +{GATE_MIN_EXPECTANCY_R}R")

    if reasons:
        return False, "; ".join(reasons)
    return True, f"MaxDD={max_dd_pct:.2f}%, PF={pf:.3f}, expectancy={exp:.4f}R"


# ---------------------------------------------------------------------------
# Main selection logic
# ---------------------------------------------------------------------------

def run_selection(dry_run: bool = False, no_ledger: bool = False) -> Dict[str, Any]:
    """Run all pre-registered gates and determine the selected candidate."""

    print("=" * 70)
    print("Automated Candidate Selection — Pre-Registered Gates")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Git SHA: {_git_head_sha()}")
    print("=" * 70)

    # Discover candidate configs
    cfg_yaml = _load_yaml(PRE_REG_YAML)
    candidate_ids = [
        c["id"] for c in cfg_yaml.get("configs", [])
        if c.get("role") == "CANDIDATE"
    ]
    print(f"\nPre-registered candidates: {candidate_ids}\n")

    from stockbot.validation import prereg_lock as _pl
    reg = _pl.enforce(PRE_REG_YAML, REGISTRY_LEDGER, gate_parameters(), len(candidate_ids))
    print(f"Pre-registration lock verified (yaml {reg['yaml_sha256'][:12]}, budget {reg['budget']}).")

    # Load trade data for all candidates
    all_trades: Dict[str, Optional[pd.DataFrame]] = {}
    all_random: Dict[str, Optional[pd.DataFrame]] = {}
    missing_data: List[str] = []

    for cfg_id in candidate_ids:
        trades = _load_trades(cfg_id)
        random = _load_random_baseline(cfg_id)
        all_trades[cfg_id] = trades
        all_random[cfg_id] = random
        if trades is None:
            missing_data.append(f"{cfg_id}: trades_candidate_{cfg_id}.csv missing")
        if random is None:
            missing_data.append(f"{cfg_id}: apples_to_apples_random_trades_{cfg_id}.csv missing")

    if missing_data:
        print("[WARN] Missing data files (bootstrap may be skipped):")
        for m in missing_data:
            print(f"  - {m}")

    # Compute trade statistics for all candidates
    all_stats: Dict[str, Dict[str, Any]] = {}
    for cfg_id in candidate_ids:
        if all_trades[cfg_id] is not None:
            all_stats[cfg_id] = _compute_trade_stats(all_trades[cfg_id], config_id=cfg_id)
        else:
            all_stats[cfg_id] = {"error": "No trade data"}

    # Gate 2: Compute 99% block-bootstrap CI on each candidate's own absolute weekly net-R.
    # This runs BEFORE the Max-T bootstrap and requires only the actual trade CSV (no random).
    # Gate 2 and Gate 3 are deliberately independent tests of different hypotheses.
    gate2_cis: Dict[str, Tuple[float, float]] = {}
    for cfg_id in candidate_ids:
        if all_trades[cfg_id] is not None:
            gate2_cis[cfg_id] = _compute_gate2_ci(all_trades[cfg_id])
        else:
            gate2_cis[cfg_id] = (float("nan"), float("nan"))

    # Run block bootstrap for all candidates jointly (only if data available)
    bootstrap_pairs = {
        cfg_id: (all_trades[cfg_id], all_random[cfg_id])
        for cfg_id in candidate_ids
        if all_trades[cfg_id] is not None and all_random[cfg_id] is not None
    }
    print(f"Running block bootstrap (B={BOOTSTRAP_REPLICATIONS}, block_sizes={GATE_FWER_BLOCK_SIZES}) ...")
    if bootstrap_pairs:
        bootstrap_results = _bootstrap_ci_and_maxt(bootstrap_pairs)
    else:
        bootstrap_results = {}
        print("  [SKIP] No candidate has both trade + random data — bootstrap skipped.")
    print()

    # Apply gates to each candidate
    gate_results: Dict[str, Dict[str, Any]] = {}
    for cfg_id in candidate_ids:
        stats = all_stats[cfg_id]
        bs_r = bootstrap_results.get(cfg_id, {})
        g = {}

        passed, msg = gate1_volume_floors(stats)
        g["gate1_volume_floors"] = {"passed": passed, "detail": msg}
        if not passed:
            g["eliminated_at_gate"] = 1
            g["elimination_reason"] = msg
            gate_results[cfg_id] = g
            continue

        # Gate 2: uses the separate block-CI on the candidate's own absolute net-R
        passed, msg = gate2_ci_lower_bound(gate2_cis[cfg_id])
        g["gate2_ci_lower_bound"] = {
            "passed": passed,
            "detail": msg,
            "ci_99_lower": gate2_cis[cfg_id][0],
            "ci_99_upper": gate2_cis[cfg_id][1],
        }
        if not passed:
            g["eliminated_at_gate"] = 2
            g["elimination_reason"] = msg
            gate_results[cfg_id] = g
            continue

        passed, msg = gate3_fwer_significance(bs_r)
        g["gate3_fwer"] = {"passed": passed, "detail": msg}
        if not passed:
            g["eliminated_at_gate"] = 3
            g["elimination_reason"] = msg
            gate_results[cfg_id] = g
            continue

        # Gates 4 and 5 applied after we identify the best candidate
        g["through_gate3"] = True
        gate_results[cfg_id] = g

    # Identify candidates that passed Gate 3
    finalists = [cid for cid, g in gate_results.items() if g.get("through_gate3")]
    print(f"Finalists after Gate 3: {finalists}")

    selected_config = None
    selection_reason = "No candidate passed all gates"

    if finalists:
        # Pick the finalist with the highest pooled net expectancy
        finalists_sorted = sorted(
            finalists,
            key=lambda cid: all_stats[cid].get("net_expectancy_r_pooled", float("-inf")),
            reverse=True,
        )
        winner_id = finalists_sorted[0]

        # Gate 4: Plateau check on the winner
        passed, msg = gate4_plateau(winner_id, all_stats)
        gate_results[winner_id]["gate4_plateau"] = {"passed": passed, "detail": msg}
        if not passed:
            gate_results[winner_id]["eliminated_at_gate"] = 4
            gate_results[winner_id]["elimination_reason"] = msg
            print(f"  Gate 4 FAILED for {winner_id}: {msg}")
        else:
            # Gate 5: Official strategy gates
            passed, msg = gate5_strategy_gates(all_stats[winner_id])
            gate_results[winner_id]["gate5_strategy"] = {"passed": passed, "detail": msg}
            if not passed:
                gate_results[winner_id]["eliminated_at_gate"] = 5
                gate_results[winner_id]["elimination_reason"] = msg
                print(f"  Gate 5 FAILED for {winner_id}: {msg}")
            else:
                selected_config = winner_id
                selection_reason = (
                    f"Highest pooled expectancy among finalists: "
                    f"{all_stats[winner_id].get('net_expectancy_r_pooled', 'N/A'):.4f}R"
                )
                print(f"\n  SELECTED: {winner_id} — {selection_reason}")

    # Build decision record
    timestamp_utc = datetime.now(timezone.utc).isoformat()
    decision: Dict[str, Any] = {
        "generated_at": timestamp_utc,
        "commit_sha": _git_head_sha(),
        "selected_config": selected_config,
        "selection_reason": selection_reason,
        "pre_registered_gate_sequence": [
            "Gate 1: Trade volume floors (pooled>=80, W1>=20, W2>=20)",
            "Gate 2: 99% block CI of candidate's own weekly net-R > 0.0R (block_size=4)",
            "Gate 3: FWER adjusted p-value <= 0.05 at both block_size=4 and block_size=8",
            "Gate 4: Plateau — every neighbor >= 75% winner expectancy AND > 0.0R",
            "Gate 5: Official gates (PF>=1.30, expectancy>=+0.15R)",
        ],
        "bootstrap_spec": {
            "method": "Westfall-Young Stepdown Max-T",
            "block_sizes": GATE_FWER_BLOCK_SIZES,
            "primary_block_size": BOOTSTRAP_BLOCK_SIZE,
            "num_replications": BOOTSTRAP_REPLICATIONS,
            "fwer_alpha": GATE_FWER_ALPHA,
        },
        "candidate_results": {
            cfg_id: {
                "trade_stats": all_stats.get(cfg_id, {}),
                "bootstrap_result": bootstrap_results.get(cfg_id, {}),
                "gate_evaluation": gate_results.get(cfg_id, {}),
            }
            for cfg_id in candidate_ids
        },
    }

    # Print summary table
    print("\n" + "=" * 84)
    print("GATE SUMMARY")
    print("=" * 84)
    header = f"{'Config':<10} {'Trades':>7} {'Exp(R)':>8} {'MaxDD%':>7} {'G2_CI':>8} {'adjP4':>7} {'adjP8':>7} {'G1':>3} {'G2':>3} {'G3':>3} {'G4':>3} {'G5':>3} Result"
    print(header)
    print("-" * 84)
    for cfg_id in candidate_ids:
        stats = all_stats.get(cfg_id, {})
        bs_r = bootstrap_results.get(cfg_id, {})
        gr = gate_results.get(cfg_id, {})
        trades_p = stats.get("trades_pooled", "?")
        exp = stats.get("net_expectancy_r_pooled", float("nan"))
        max_dd = stats.get("max_drawdown_pct", float("nan"))
        # Gate 2: show absolute net-R CI lower bound (from gate2_cis, not from Max-T output)
        ci_lo = gate2_cis.get(cfg_id, (float("nan"), float("nan")))[0]
        adj_p4 = bs_r.get(4, {}).get("adjusted_p_value", float("nan"))
        adj_p8 = bs_r.get(8, {}).get("adjusted_p_value", float("nan"))
        g1 = "Y" if gr.get("gate1_volume_floors", {}).get("passed") else "N"
        g2 = "Y" if gr.get("gate2_ci_lower_bound", {}).get("passed") else ("?" if "gate2_ci_lower_bound" not in gr else "N")
        g3 = "Y" if gr.get("gate3_fwer", {}).get("passed") else ("?" if "gate3_fwer" not in gr else "N")
        g4 = "Y" if gr.get("gate4_plateau", {}).get("passed") else ("?" if "gate4_plateau" not in gr else "N")
        g5 = "Y" if gr.get("gate5_strategy", {}).get("passed") else ("?" if "gate5_strategy" not in gr else "N")
        result = "SELECTED" if cfg_id == selected_config else gr.get("elimination_reason", "")[:25]
        dd_str = f"{max_dd:>6.2f}%" if not np.isnan(max_dd) else "   NaN%"
        print(
            f"{cfg_id:<10} {str(trades_p):>7} {exp:>8.4f} {dd_str} {ci_lo:>8.4f} {adj_p4:>7.4f} {adj_p8:>7.4f} "
            f"{g1:>3} {g2:>3} {g3:>3} {g4:>3} {g5:>3} {result}"
        )
    print("-" * 84)
    if selected_config:
        print(f"\n>>> FINAL SELECTION: {selected_config}")
    else:
        print(f"\n>>> NO CANDIDATE SELECTED — {selection_reason}")
    print()

    gate_reached_map = {
        cid: gate_results.get(cid, {}).get("eliminated_at_gate", 5 if cid == selected_config else "?")
        for cid in candidate_ids
    }
    if dry_run:
        _log_exploratory("dry-run", selected_config, gate_reached_map)
        print("[DRY RUN] Decision and ledger NOT written (run recorded in trial_ledger_exploratory.csv).")
        return decision

    # Write decision file
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(DECISION_FILE, "w", encoding="utf-8") as f:
        json.dump(decision, f, indent=2, default=str)
    print(f"Decision written to: {DECISION_FILE}")

    if no_ledger:
        _log_exploratory("no-ledger diagnostic", selected_config, gate_reached_map)
        print("[NO-LEDGER] Trial ledger NOT updated (recorded in trial_ledger_exploratory.csv).")
        return decision

    # Append to the hash-chained trial ledger
    row = {"timestamp_utc": timestamp_utc, "commit_sha": _git_head_sha(), "selected_config": selected_config or "NONE",
           "selection_reason": selection_reason, "row_type": "SELECTION", "yaml_sha256": reg["yaml_sha256"],
           "gates_sha256": reg["gates_sha256"], "budget": reg["budget"]}
    row.update({f"{cid}_gate_reached": gate_reached_map[cid] for cid in candidate_ids})
    _pl.append_row(REGISTRY_LEDGER, row)
    print(f"Trial ledger updated: {REGISTRY_LEDGER}")

    return decision


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated pre-registered candidate selection for StockBot."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute selection without writing decision file or ledger.",
    )
    parser.add_argument("--outputs-dir", type=str, default=None,
                        help="Read inputs from / write decision to this folder instead of backtest/outputs.")
    parser.add_argument("--no-ledger", action="store_true",
                        help="Do not append to the trial ledger (use for recomputed/diagnostic folders).")
    parser.add_argument("--register", action="store_true",
                        help="Record the pre-registration hash (YAML + gate parameters + config budget) in the ledger.")
    parser.add_argument("--reregister-reason", type=str, default=None,
                        help="Required to register again after one exists; the reason is stored in the ledger.")
    args = parser.parse_args()
    if args.register:
        register(args.reregister_reason)
        return
    if args.outputs_dir:
        configure_outputs(Path(args.outputs_dir))
    run_selection(dry_run=args.dry_run, no_ledger=args.no_ledger)


if __name__ == "__main__":
    main()
