"""backtest/audit_generator.py — Evaluates strategy gates and generates audit.json."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from engine_core.trade_metrics import metrics_from_trades, sharpe_from_equity

_ROOT = Path(__file__).resolve().parents[1]


def _git(*a: str) -> str:
    try:
        return subprocess.check_output(["git", *a], text=True, cwd=_ROOT).strip()
    except Exception:
        return "unknown"


def summarize(res, nifty: pd.Series, cfg: dict, initial: float) -> dict:
    """Compute performance and gate metrics for a single simulation result."""
    g = cfg["gates"]
    eq = res.equity
    if len(eq) < 2:
        return {"n_trades": 0, "compliance_applied": getattr(res, "compliance_applied", False)}

    years = max((pd.to_datetime(eq.index[-1]) - pd.to_datetime(eq.index[0])).days / 365.25, 1e-9)
    tax = float(res.trades["tax_est"].sum()) if len(res.trades) and "tax_est" in res.trades.columns else 0.0
    final_after_tax = float(eq.iloc[-1]) - tax
    cagr = ((final_after_tax / initial) ** (1 / years) - 1) * 100

    if len(nifty) >= 2:
        n0, n1 = float(nifty.iloc[0]), float(nifty.iloc[-1])
        n_net_end = n1 - max(0.0, n1 - n0) * g["ltcg_tax_pct"] / 100
        n_cagr = ((n_net_end / n0) ** (1 / years) - 1) * 100
    else:
        n_cagr = 0.0

    dd = float(((eq.cummax() - eq) / eq.cummax()).max() * 100) if len(eq) else 0.0
    m = metrics_from_trades(res.trades, initial) if len(res.trades) else {"n_trades": 0}

    return {
        **m,
        "cagr_after_tax_pct": cagr,
        "nifty_cagr_after_tax_pct": n_cagr,
        "alpha_after_tax_pct": cagr - n_cagr,
        "max_drawdown_pct": dd,
        "sharpe": sharpe_from_equity(eq, g["risk_free_pct"] / 100),
        "compliance_applied": getattr(res, "compliance_applied", False),
    }


def generate(summaries: dict, cfg: dict, out_dir: Optional[Path] = None) -> dict:
    """Evaluate gates across all summarized windows and write audit.json + audit.sha256."""
    if out_dir is None:
        out_dir = Path(__file__).parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    g, ok_all, per = cfg["gates"], True, {}
    for name, m in summaries.items():
        checks = {
            "max_drawdown": m.get("max_drawdown_pct", 99) < g["max_drawdown_pct"],
            "alpha_after_tax": m.get("alpha_after_tax_pct", -99) >= g["min_alpha_after_tax_pct"],
            "expectancy": m.get("expectancy_r", -9) >= g["min_expectancy_r"],
            "profit_factor": m.get("profit_factor", 0) >= g["min_profit_factor"],
            "min_trades": m.get("n_trades", 0) >= g["min_trades"],
            "compliance_applied": bool(m.get("compliance_applied")),
        }
        per[name] = checks
        ok_all &= all(checks.values())

    cfg_sha = _git("hash-object", "strategy_config.yaml")
    commit_sha = _git("rev-parse", "HEAD")
    working_tree_clean = _git("status", "--porcelain") == ""

    audit = {
        "audit_generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "strategy_config_sha": cfg_sha,
        "commit_sha": commit_sha,
        "working_tree_clean": working_tree_clean,
        "metrics": summaries,
        "checks": per,
        "dual_gate": {"overall_pass": ok_all},
        "eligible_for_deployment": bool(ok_all),
    }

    p = out_dir / "audit.json"
    p.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    audit_sha = hashlib.sha256(p.read_bytes()).hexdigest()
    audit["audit_sha256"] = audit_sha
    (out_dir / "audit.sha256").write_text(audit_sha, encoding="utf-8")
    return audit


class AuditGenerator:
    """Compatibility wrapper class for generate()."""

    def generate(self, pass2_results_per_regime: dict[str, dict], config: dict, out_dir: Optional[Path] = None) -> dict:
        return generate(pass2_results_per_regime, config, out_dir)
