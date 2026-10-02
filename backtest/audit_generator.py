"""
FInsight Trading Engine — Audit Generator
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

class AuditGenerator:
    """
    Generates audit.json from Pass 2 results.
    This file is read by authorize_live.py to gate live deployment.
    """

    def generate(self, pass2_results_per_regime: dict[str, dict], config: dict) -> dict:
        
        # Get git SHA of strategy_config.yaml
        config_path = Path(__file__).resolve().parents[1] / "strategy_config.yaml"
        try:
            sha = subprocess.check_output(["git", "hash-object", str(config_path)]).decode("utf-8").strip()
        except Exception:
            sha = "unknown"

        audit = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "strategy_config_sha": sha,
            "regimes": {},
            "dual_gate": {
                "max_drawdown_pass": True,
                "outperformance_pass": True,
                "overall_pass": True
            },
            "eligible_for_deployment": True
        }

        max_dd_limit = config["backtest"]["pass_criteria"]["max_drawdown_pct"]
        must_outperform = config["backtest"]["pass_criteria"]["must_outperform_nifty"]

        for regime, data in pass2_results_per_regime.items():
            summary = data.get("summary", {})
            audit["regimes"][regime] = summary
            
            dd = summary.get("max_drawdown_pct", 0)
            alpha = summary.get("alpha_pct", 0)
            
            if dd >= max_dd_limit:
                audit["dual_gate"]["max_drawdown_pass"] = False
            
            if must_outperform and alpha <= 0:
                audit["dual_gate"]["outperformance_pass"] = False

        if not audit["dual_gate"]["max_drawdown_pass"] or not audit["dual_gate"]["outperformance_pass"]:
            audit["dual_gate"]["overall_pass"] = False
            audit["eligible_for_deployment"] = False

        # Write to file
        out_dir = Path(__file__).parent / "outputs"
        out_dir.mkdir(exist_ok=True)
        
        with open(out_dir / "audit.json", "w", encoding="utf-8") as f:
            json.dump(audit, f, indent=2)
            
        return audit
