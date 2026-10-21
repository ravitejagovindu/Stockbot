"""scripts/paper_report.py — Weekly Report & Criteria Evaluation for Paper Trading.

Evaluates paper trading performance against strategy_config.yaml paper_criteria and
the backtest baseline. Outputs summary table and docs/PAPER_RESULT.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
from sqlalchemy import text

# Add project root to sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import load_config
from data.db.connection import get_session
from engine_core.trade_metrics import metrics_from_trades, trades_from_log
from live_runner.git_lock import read_authorized_info


def load_backtest_baseline(audit_path: Path) -> Dict[str, float]:
    """Load baseline metrics from backtest audit.json averaged across regimes."""
    if not audit_path.exists():
        return {"expectancy_r": 0.0, "win_rate_pct": 0.0}
    try:
        with open(audit_path, "r", encoding="utf-8") as f:
            audit = json.load(f)
        metrics = audit.get("metrics", {})
        if not metrics:
            return {"expectancy_r": 0.0, "win_rate_pct": 0.0}
        exp_list = [m.get("expectancy_r", 0.0) for m in metrics.values() if "expectancy_r" in m]
        win_list = [m.get("win_rate_pct", 0.0) for m in metrics.values() if "win_rate_pct" in m]
        return {
            "expectancy_r": float(np.mean(exp_list)) if exp_list else 0.0,
            "win_rate_pct": float(np.mean(win_list)) if win_list else 0.0,
        }
    except Exception:
        return {"expectancy_r": 0.0, "win_rate_pct": 0.0}


def evaluate_paper_performance(
    config: dict,
    audit_file: Path | None = None,
    output_file: Path | None = None,
) -> Dict[str, Any]:
    criteria = config.get("paper_criteria", {})
    min_days = int(criteria.get("min_days", 90))
    min_closed_trades = int(criteria.get("min_closed_trades", 60))
    max_expectancy_gap_r = float(criteria.get("max_expectancy_gap_r", 0.25))
    max_win_rate_gap_pts = float(criteria.get("max_win_rate_gap_pts", 12.0))
    min_profit_factor = float(criteria.get("min_profit_factor", 1.2))
    max_drawdown_pct = float(criteria.get("max_drawdown_pct", 12.0))
    max_skipped_ticket_rate = float(criteria.get("max_skipped_ticket_rate", 0.40))

    start_equity = float(config.get("runtime", {}).get("paper_start_equity", 1_000_000.0))

    # Read authorized info to determine paper start date
    auth_info = read_authorized_info()
    authorized_at_str = auth_info.get("authorized_at")
    authorized_date = None
    if authorized_at_str:
        try:
            authorized_date = date.fromisoformat(authorized_at_str[:10])
        except Exception:
            pass

    with get_session() as s:
        df = trades_from_log(s, mode="PAPER")
        if authorized_date and not df.empty and "entry_date" in df.columns:
            df = df[pd.to_datetime(df["entry_date"]).dt.date >= authorized_date]

        metrics = metrics_from_trades(df, start_equity)
        n_trades = metrics.get("n_trades", 0)

        # Duration in days
        if authorized_date:
            days_count = (date.today() - authorized_date).days
        elif not df.empty and "entry_date" in df.columns:
            min_d = pd.to_datetime(df["entry_date"]).dt.date.min()
            max_d = pd.to_datetime(df["exit_date"]).dt.date.max() if "exit_date" in df.columns else date.today()
            days_count = (max_d - min_d).days
        else:
            days_count = 0

        # Skipped ticket rate: SKIPPED / (OPENED + SKIPPED)
        opened_cnt = s.execute(text("SELECT COUNT(*) FROM daily_watchlist WHERE execution_status = 'OPENED'")).scalar() or 0
        skipped_cnt = s.execute(text("SELECT COUNT(*) FROM daily_watchlist WHERE execution_status = 'SKIPPED'")).scalar() or 0
        total_decided = opened_cnt + skipped_cnt
        skipped_rate = float(skipped_cnt / total_decided) if total_decided > 0 else 0.0

    # Backtest baseline
    if audit_file is None:
        audit_file = _ROOT / "backtest" / "outputs" / "audit.json"
    baseline = load_backtest_baseline(audit_file)
    baseline_exp = baseline["expectancy_r"]
    baseline_win = baseline["win_rate_pct"]

    paper_exp = float(metrics.get("expectancy_r", 0.0))
    paper_win = float(metrics.get("win_rate_pct", 0.0))
    pf = float(metrics.get("profit_factor", 0.0))
    dd = float(metrics.get("max_drawdown_pct_trade_level", 0.0))

    exp_gap = abs(paper_exp - baseline_exp)
    win_gap = abs(paper_win - baseline_win)

    # Check criteria (D4: OR condition for duration/trades)
    duration_passed = bool((days_count >= min_days) or (n_trades >= min_closed_trades))
    exp_passed = bool(exp_gap <= max_expectancy_gap_r)
    win_passed = bool(win_gap <= max_win_rate_gap_pts)
    pf_passed = bool(pf >= min_profit_factor)
    dd_passed = bool(dd < max_drawdown_pct)
    skip_passed = bool(skipped_rate < max_skipped_ticket_rate)

    overall_pass = bool(
        duration_passed
        and exp_passed
        and win_passed
        and pf_passed
        and dd_passed
        and skip_passed
        and n_trades > 0
    )

    result_data = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "passed": overall_pass,
        "metrics": {
            "days_count": days_count,
            "n_closed_trades": n_trades,
            "expectancy_r": round(paper_exp, 3),
            "baseline_expectancy_r": round(baseline_exp, 3),
            "expectancy_gap_r": round(exp_gap, 3),
            "win_rate_pct": round(paper_win, 2),
            "baseline_win_rate_pct": round(baseline_win, 2),
            "win_rate_gap_pts": round(win_gap, 2),
            "profit_factor": round(pf, 2) if np.isfinite(pf) else "inf",
            "max_drawdown_pct": round(dd, 2),
            "skipped_ticket_rate": round(skipped_rate, 3),
        },
        "checks": {
            "duration_or_trades": duration_passed,
            "expectancy_gap": exp_passed,
            "win_rate_gap": win_passed,
            "profit_factor": pf_passed,
            "max_drawdown": dd_passed,
            "skipped_ticket_rate": skip_passed,
        },
        "thresholds": {
            "min_days": min_days,
            "min_closed_trades": min_closed_trades,
            "max_expectancy_gap_r": max_expectancy_gap_r,
            "max_win_rate_gap_pts": max_win_rate_gap_pts,
            "min_profit_factor": min_profit_factor,
            "max_drawdown_pct": max_drawdown_pct,
            "max_skipped_ticket_rate": max_skipped_ticket_rate,
        },
    }

    if output_file is None:
        output_file = _ROOT / "docs" / "PAPER_RESULT.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2)

    return result_data


def print_report(res: Dict[str, Any]) -> None:
    m = res["metrics"]
    c = res["checks"]
    t = res["thresholds"]

    print("\n+----------------------------------------------------------------+")
    print(f"|           StockBot -- Paper Trading Evaluation Report          |")
    status_msg = "PASSED (Gate G4 Complete)" if res["passed"] else "IN PROGRESS / PENDING CRITERIA"
    print(f"|  Status: {status_msg:<52} |")
    print("+----------------------------------------------------------------+\n")

    print(f"Evaluated At: {res['evaluated_at']}")
    print(f"Days Active:  {m['days_count']} days (Threshold: >= {t['min_days']} days OR >= {t['min_closed_trades']} trades)")
    print(f"Closed Trades:{m['n_closed_trades']}")
    print("\nCriteria Evaluation:")
    print("--------------------------------------------------------------------------------")
    print(f"{'Criterion':<28} | {'Threshold':<18} | {'Paper Value':<14} | {'Status':<6}")
    print("--------------------------------------------------------------------------------")
    dur_str = f"{m['days_count']}d / {m['n_closed_trades']}t"
    exp_str = f"{m['expectancy_gap_r']} R"
    win_str = f"{m['win_rate_gap_pts']} pts"
    pf_str = str(m['profit_factor'])
    dd_str = f"{m['max_drawdown_pct']} %"
    skip_str = f"{m['skipped_ticket_rate'] * 100:.1f} %"

    t_exp = f"<= {t['max_expectancy_gap_r']} R"
    t_win = f"<= {t['max_win_rate_gap_pts']} pts"
    t_pf = f">= {t['min_profit_factor']}"
    t_dd = f"< {t['max_drawdown_pct']} %"
    t_skip = f"< {t['max_skipped_ticket_rate'] * 100:.0f} %"

    print(f"{'Duration / Min Trades (D4)':<28} | {'>= 90d OR >= 60t':<18} | {dur_str:<14} | {'PASS' if c['duration_or_trades'] else 'FAIL'}")
    print(f"{'Expectancy Gap (|P-BT|)':<28} | {t_exp:<18} | {exp_str:<14} | {'PASS' if c['expectancy_gap'] else 'FAIL'}")
    print(f"{'Win Rate Gap (|P-BT|)':<28} | {t_win:<18} | {win_str:<14} | {'PASS' if c['win_rate_gap'] else 'FAIL'}")
    print(f"{'Profit Factor':<28} | {t_pf:<18} | {pf_str:<14} | {'PASS' if c['profit_factor'] else 'FAIL'}")
    print(f"{'Max Drawdown':<28} | {t_dd:<18} | {dd_str:<14} | {'PASS' if c['max_drawdown'] else 'FAIL'}")
    print(f"{'Skipped Ticket Rate':<28} | {t_skip:<18} | {skip_str:<14} | {'PASS' if c['skipped_ticket_rate'] else 'FAIL'}")
    print("--------------------------------------------------------------------------------")
    overall_msg = "[PASS] ALL CRITERIA MET (Eligible for Gate G5 Review)" if res['passed'] else "[PENDING] CRITERIA NOT YET MET (Continue paper trading)"
    print(f"Overall Result: {overall_msg}\n")
    print(f"Wrote result to docs/PAPER_RESULT.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Paper Trading Performance")
    parser.add_argument("--json", action="store_true", help="Output raw JSON only")
    args = parser.parse_args()

    cfg = load_config()
    result = evaluate_paper_performance(cfg)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
