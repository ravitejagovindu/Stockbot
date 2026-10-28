"""
backtest/run_candidate_simulations.py — Automated Config-Override Runner for Pre-Registered Configurations.
=======================================================================================================
Reads configuration overrides from backtest/pre_registered_configs.yaml, constructs candidate-specific
strategy configurations, and executes Simulator over W1 (2020-2021), W2 (2022-2026), and Pooled windows.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import logging
from pathlib import Path
import sys
import yaml
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.simulator import Simulator
from config import load_config
from data.db.connection import get_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("candidate_runner")

OUTPUT_DIR = ROOT / "backtest" / "outputs"
YAML_PATH = ROOT / "backtest" / "pre_registered_configs.yaml"


def load_registered_configs() -> dict:
    """Load the pre-registered configurations YAML."""
    if not YAML_PATH.exists():
        raise FileNotFoundError(f"Missing pre-registered configurations: {YAML_PATH}")
    with open(YAML_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_config_for(base_cfg: dict, config_entry: dict) -> dict:
    """Construct deep-copied strategy configuration with overrides applied."""
    cfg = deepcopy(base_cfg)

    # Apply entry_filters section overrides
    if "entry_filters" in config_entry:
        if "entry_filters" not in cfg:
            cfg["entry_filters"] = {}
        for k, v in config_entry["entry_filters"].items():
            cfg["entry_filters"][k] = v

    # Apply execution section overrides
    if "execution" in config_entry:
        if "execution" not in cfg:
            cfg["execution"] = {}
        for k, v in config_entry["execution"].items():
            cfg["execution"][k] = v

    return cfg


def run_single_config(
    cid: str,
    config_entry: dict,
    base_cfg: dict,
    session,
    initial_equity: float = 1_000_000.0,
) -> dict:
    """Execute Simulator for a single candidate configuration across W1 and W2."""
    cfg = build_config_for(base_cfg, config_entry)
    sim = Simulator(cfg, session)

    w1_start, w1_end = date(2020, 1, 1), date(2021, 12, 31)
    w2_start, w2_end = date(2022, 1, 1), date(2026, 10, 16)

    logger.info(f"[{cid}] Executing Window 1 ({w1_start} to {w1_end})...")
    res_w1 = sim.run(w1_start, w1_end, initial_equity=initial_equity)
    df_w1 = res_w1.trades
    df_w1["window"] = "W1 (2020-21)"
    df_w1["config_id"] = cid

    logger.info(f"[{cid}] Executing Window 2 ({w2_start} to {w2_end})...")
    res_w2 = sim.run(w2_start, w2_end, initial_equity=initial_equity)
    df_w2 = res_w2.trades
    df_w2["window"] = "W2 (2022-26)"
    df_w2["config_id"] = cid

    df_pooled = pd.concat([df_w1, df_w2], ignore_index=True)

    # Save output artifacts
    w1_path = OUTPUT_DIR / f"trades_{cid}_window_2020_2021.csv"
    w2_path = OUTPUT_DIR / f"trades_{cid}_window_2022_2026.csv"
    pooled_path = OUTPUT_DIR / f"trades_{cid}_pooled.csv"

    df_w1.to_csv(w1_path, index=False)
    df_w2.to_csv(w2_path, index=False)
    df_pooled.to_csv(pooled_path, index=False)

    logger.info(f"[{cid}] Completed: W1={len(df_w1)} trades, W2={len(df_w2)} trades, Pooled={len(df_pooled)} trades.")
    return {
        "config_id": cid,
        "name": config_entry.get("name", cid),
        "w1_trades": len(df_w1),
        "w2_trades": len(df_w2),
        "pooled_trades": len(df_pooled),
        "w1_pnl": float(df_w1["pnl_net"].sum()) if not df_w1.empty else 0.0,
        "w2_pnl": float(df_w2["pnl_net"].sum()) if not df_w2.empty else 0.0,
        "pooled_pnl": float(df_pooled["pnl_net"].sum()) if not df_pooled.empty else 0.0,
        "w1_r": float(df_w1["realized_r"].mean()) if not df_w1.empty else 0.0,
        "w2_r": float(df_w2["realized_r"].mean()) if not df_w2.empty else 0.0,
        "pooled_r": float(df_pooled["realized_r"].mean()) if not df_pooled.empty else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description="Run simulation for pre-registered candidate configs.")
    parser.add_argument("--config", type=str, help="Specific config ID to run (e.g. CFG-01)")
    parser.add_argument("--all", action="store_true", help="Run all 6 candidate configurations")
    parser.add_argument("--list", action="store_true", help="List registered configurations")
    args = parser.parse_args()

    reg_data = load_registered_configs()
    configs_list = reg_data.get("configs", [])

    if args.list:
        print("\n=== PRE-REGISTERED CONFIGURATIONS ===")
        for c in configs_list:
            role = c.get("role", "CANDIDATE")
            print(f"- {c['id']}: [{role}] {c.get('name', '')}")
            print(f"    Filters: {c.get('entry_filters', {})}")
            print(f"    Execution: {c.get('execution', {})}")
        return

    configs_dict = {c["id"]: c for c in configs_list}
    base_cfg = load_config()

    if args.config:
        cid = args.config.upper()
        if cid not in configs_dict:
            print(f"Error: Unknown configuration '{cid}'. Available: {list(configs_dict.keys())}")
            sys.exit(1)
        target_configs = [configs_dict[cid]]
    elif args.all:
        target_configs = [c for c in configs_list if c.get("role") == "CANDIDATE"]
    else:
        parser.print_help()
        return

    results = []
    with get_session() as s:
        for centry in target_configs:
            cid = centry["id"]
            res = run_single_config(cid, centry, base_cfg, s)
            results.append(res)

    print("\n" + "=" * 95)
    print("  SIMULATION RESULTS SUMMARY")
    print("=" * 95)
    print(pd.DataFrame(results).to_string(index=False))


if __name__ == "__main__":
    main()
