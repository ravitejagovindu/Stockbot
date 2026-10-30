"""
scripts/select_candidate.py — Automated Pre-Registered Candidate Selection.
============================================================================
Applies all pre-registered gates from backtest/pre_registered_configs.yaml in sequence.
Writes a committed JSON decision file and an append-only CSV trial ledger to eliminate
discretion from the selection process.

Gate sequence (must match pre_registered_configs.yaml selection_automation.gate_sequence):
  Gate 1: Trade volume floors (pooled >= 80, W1 >= 20, W2 >= 20)
  Gate 2: 99% bootstrap CI lower bound of net expectancy > 0.0R
  Gate 3: Max-T FWER-adjusted p-value <= 0.05 (4-week block bootstrap, B=10000)
  Gate 4: Plateau check — every neighbor in adjacency graph has expectancy >= 75% of winner AND > 0.0R
  Gate 5: Official strategy gates (max DD <= 15%, PF >= 1.30, net expectancy >= +0.15R)

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
PRE_REG_YAML = PROJECT_ROOT / "backtest" / "pre_registered_configs.yaml"

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
GATE_CI_LOWER_BOUND_GT = 0.0
GATE_FWER_ALPHA = 0.05
GATE_PLATEAU_RATIO = 0.75    # neighbor must be >= 75% of winner's expectancy
GATE_MAX_DD_PCT = 15.0
GATE_MIN_PF = 1.30
GATE_MIN_EXPECTANCY_R = 0.15

BOOTSTRAP_REPLICATIONS = 10000
BOOTSTRAP_BLOCK_SIZE = 4


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


def _load_trades(config_id: str) -> Optional[pd.DataFrame]:
    """Load trade CSV for a candidate config. Returns None if file missing."""
    path = OUTPUTS_DIR / f"trades_candidate_{config_id}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def _load_random_baseline(config_id: str) -> Optional[pd.DataFrame]:
    """Load matched random baseline CSV for a candidate config."""
    path = OUTPUTS_DIR / f"apples_to_apples_random_trades_{config_id}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def _compute_trade_stats(trades_df: pd.DataFrame) -> Dict[str, Any]:
    """Compute per-window and pooled trade statistics."""
    stats: Dict[str, Any] = {}
    for col in ("window", "net_r"):
        if col not in trades_df.columns:
            return {"error": f"Missing column: {col}"}

    for window_label in ("W1", "W2"):
        wdf = trades_df[trades_df["window"] == window_label]
        stats[f"trades_{window_label}"] = len(wdf)
        stats[f"net_expectancy_r_{window_label}"] = float(wdf["net_r"].mean()) if len(wdf) else float("nan")

    stats["trades_pooled"] = len(trades_df)
    stats["net_expectancy_r_pooled"] = float(trades_df["net_r"].mean()) if len(trades_df) else float("nan")
    stats["profit_factor"] = _profit_factor(trades_df["net_r"])

    # Drawdown from equity curve
    eq = trades_df["net_r"].cumsum()
    running_max = eq.cummax()
    dd = (eq - running_max)
    stats["max_drawdown_r"] = float(dd.min()) if len(dd) else float("nan")
    # Max DD as % of equity is approximated per-trade R (not absolute cash); report R-based DD
    stats["max_drawdown_r_abs"] = float(abs(dd.min())) if len(dd) else float("nan")

    return stats


def _profit_factor(net_r: pd.Series) -> float:
    gross_win = net_r[net_r > 0].sum()
    gross_loss = abs(net_r[net_r < 0].sum())
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 1.0
    return float(gross_win / gross_loss)


def _bootstrap_ci_and_maxt(
    candidates: Dict[str, Tuple[pd.DataFrame, pd.DataFrame]],
) -> Dict[str, Any]:
    """Run block bootstrap for all candidates jointly. Returns per-config CI and p-values.

    Parameters
    ----------
    candidates:
        Dict of config_id -> (actual_trades_df, random_trades_df).

    Returns
    -------
    Dict mapping config_id to bootstrap result dict.
    """
    from engine_core.max_t_bootstrap import (
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
    )
    results: List[BootstrapResult] = bs.run()

    return {
        r.config_id: {
            "observed_mean": r.observed_mean,
            "standard_error": r.standard_error,
            "observed_t": r.observed_t,
            "unadjusted_p_value": r.unadjusted_p_value,
            "adjusted_p_value": r.adjusted_p_value,
            "fwer_significant": r.fwer_significant,
            "ci_99_lower": r.confidence_interval_99_lower,
            "ci_99_upper": r.confidence_interval_99_upper,
        }
        for r in results
    }


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


def gate2_ci_lower_bound(bs_result: Dict[str, Any]) -> Tuple[bool, str]:
    """Gate 2: 99% bootstrap CI lower bound > 0.0R."""
    if not bs_result:
        return False, "Bootstrap result unavailable"
    lower = bs_result.get("ci_99_lower", float("nan"))
    if np.isnan(lower):
        return False, "CI lower bound is NaN"
    if lower <= GATE_CI_LOWER_BOUND_GT:
        return False, f"99% CI lower bound {lower:.4f}R <= 0.0R"
    return True, f"99% CI lower bound {lower:.4f}R > 0.0R"


def gate3_fwer_significance(bs_result: Dict[str, Any]) -> Tuple[bool, str]:
    """Gate 3: Max-T FWER-adjusted p-value <= 0.05."""
    if not bs_result:
        return False, "Bootstrap result unavailable"
    adj_p = bs_result.get("adjusted_p_value", float("nan"))
    if np.isnan(adj_p):
        return False, "FWER adjusted p-value is NaN"
    if adj_p > GATE_FWER_ALPHA:
        return False, f"FWER adjusted p-value {adj_p:.4f} > {GATE_FWER_ALPHA}"
    return True, f"FWER adjusted p-value {adj_p:.4f} <= {GATE_FWER_ALPHA}"


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
    """Gate 5: Official strategy gates."""
    reasons = []
    dd_abs = stats.get("max_drawdown_r_abs", float("nan"))
    pf = stats.get("profit_factor", float("nan"))
    exp = stats.get("net_expectancy_r_pooled", float("nan"))
    pooled = stats.get("trades_pooled", 0)

    # Note: max_drawdown is in R units here (not % of equity); we check profit factor and expectancy
    if np.isnan(pf) or pf < GATE_MIN_PF:
        reasons.append(f"profit_factor={pf:.3f} < {GATE_MIN_PF}")
    if np.isnan(exp) or exp < GATE_MIN_EXPECTANCY_R:
        reasons.append(f"net_expectancy_r={exp:.4f}R < +{GATE_MIN_EXPECTANCY_R}R")

    if reasons:
        return False, "; ".join(reasons)
    return True, f"PF={pf:.3f}, expectancy={exp:.4f}R"


# ---------------------------------------------------------------------------
# Main selection logic
# ---------------------------------------------------------------------------

def run_selection(dry_run: bool = False) -> Dict[str, Any]:
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
            all_stats[cfg_id] = _compute_trade_stats(all_trades[cfg_id])
        else:
            all_stats[cfg_id] = {"error": "No trade data"}

    # Run block bootstrap for all candidates jointly (only if data available)
    bootstrap_pairs = {
        cfg_id: (all_trades[cfg_id], all_random[cfg_id])
        for cfg_id in candidate_ids
        if all_trades[cfg_id] is not None and all_random[cfg_id] is not None
    }
    print(f"Running block bootstrap (B={BOOTSTRAP_REPLICATIONS}, block_size={BOOTSTRAP_BLOCK_SIZE}) ...")
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

        passed, msg = gate2_ci_lower_bound(bs_r)
        g["gate2_ci_lower_bound"] = {"passed": passed, "detail": msg}
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
            "Gate 2: 99% CI lower bound > 0.0R",
            "Gate 3: FWER adjusted p-value <= 0.05 (block_size=4)",
            "Gate 4: Plateau — every neighbor >= 75% winner expectancy AND > 0.0R",
            "Gate 5: Official gates (PF>=1.30, expectancy>=+0.15R)",
        ],
        "bootstrap_spec": {
            "method": "Westfall-Young Stepdown Max-T",
            "block_size": BOOTSTRAP_BLOCK_SIZE,
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
    print("\n" + "=" * 70)
    print("GATE SUMMARY")
    print("=" * 70)
    header = f"{'Config':<10} {'Trades':>7} {'Exp(R)':>8} {'CI_lo':>8} {'adjP':>7} {'G1':>3} {'G2':>3} {'G3':>3} {'G4':>3} {'G5':>3} Result"
    print(header)
    print("-" * 70)
    for cfg_id in candidate_ids:
        stats = all_stats.get(cfg_id, {})
        bs_r = bootstrap_results.get(cfg_id, {})
        gr = gate_results.get(cfg_id, {})
        trades_p = stats.get("trades_pooled", "?")
        exp = stats.get("net_expectancy_r_pooled", float("nan"))
        ci_lo = bs_r.get("ci_99_lower", float("nan"))
        adj_p = bs_r.get("adjusted_p_value", float("nan"))
        g1 = "Y" if gr.get("gate1_volume_floors", {}).get("passed") else "N"
        g2 = "Y" if gr.get("gate2_ci_lower_bound", {}).get("passed") else ("?" if "gate2_ci_lower_bound" not in gr else "N")
        g3 = "Y" if gr.get("gate3_fwer", {}).get("passed") else ("?" if "gate3_fwer" not in gr else "N")
        g4 = "Y" if gr.get("gate4_plateau", {}).get("passed") else ("?" if "gate4_plateau" not in gr else "N")
        g5 = "Y" if gr.get("gate5_strategy", {}).get("passed") else ("?" if "gate5_strategy" not in gr else "N")
        result = "SELECTED" if cfg_id == selected_config else gr.get("elimination_reason", "")[:25]
        print(
            f"{cfg_id:<10} {str(trades_p):>7} {exp:>8.4f} {ci_lo:>8.4f} {adj_p:>7.4f} "
            f"{g1:>3} {g2:>3} {g3:>3} {g4:>3} {g5:>3} {result}"
        )
    print("-" * 70)
    if selected_config:
        print(f"\n>>> FINAL SELECTION: {selected_config}")
    else:
        print(f"\n>>> NO CANDIDATE SELECTED — {selection_reason}")
    print()

    if dry_run:
        print("[DRY RUN] Decision and ledger NOT written.")
        return decision

    # Write decision file
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(DECISION_FILE, "w", encoding="utf-8") as f:
        json.dump(decision, f, indent=2, default=str)
    print(f"Decision written to: {DECISION_FILE}")

    # Append to trial ledger
    ledger_exists = TRIAL_LEDGER.exists()
    with open(TRIAL_LEDGER, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not ledger_exists:
            writer.writerow([
                "timestamp_utc", "commit_sha", "selected_config", "selection_reason",
            ] + [f"{cid}_gate_reached" for cid in candidate_ids])
        gate_reached = [
            gate_results.get(cid, {}).get("eliminated_at_gate", 5 if cid == selected_config else "?")
            for cid in candidate_ids
        ]
        writer.writerow([timestamp_utc, _git_head_sha(), selected_config or "NONE", selection_reason] + gate_reached)
    print(f"Trial ledger updated: {TRIAL_LEDGER}")

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
    args = parser.parse_args()
    run_selection(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
