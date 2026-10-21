"""FInsight Trading Engine — Live Deployment Authorization Script.

Run this ONCE after a successful Pass 2 backtest to authorize trading (PAPER or LIVE).

Usage:
    python authorize_live.py --confirm-ledger=backtest/outputs/audit.json

This script:
1. Reads and validates audit.json against strategy_config.yaml hash and audit.sha256.
2. Re-computes all dual gates from scratch against strategy_config.yaml criteria.
3. If mode is LIVE, requires docs/PAPER_RESULT.json demonstrating paper criteria pass.
4. Verifies a clean git working tree.
5. Captures the current HEAD SHA and writes authorized_deployment.json.
6. Commits authorized_deployment.json to Git.

After running this, the live EOD runner is permitted to execute.
Any code change after this will break the SHA lock and require re-authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import load_config
from engine_core.mode import current_mode

BASE_DIR = Path(__file__).resolve().parent
AUTHORIZED_FILE = BASE_DIR / "authorized_deployment.json"


def run_git(args: list[str]) -> str:
    """Run git command, return stdout. Exits on failure."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        print(f"[ERROR] git {' '.join(args)} failed:\n{result.stderr}")
        sys.exit(1)
    return result.stdout.strip()


def sha256_file(p: Path) -> str:
    """Compute sha256 of file at path."""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def validate_audit(audit_path: Path, cfg: dict) -> dict:
    """Load, recompute, and validate audit.json. Returns audit dict if valid."""
    if not audit_path.exists():
        print(f"[ERROR] audit.json not found at: {audit_path}")
        print("  → Run the backtest first: python -m backtest.run_backtest --pass2 --audit")
        sys.exit(1)

    sha_path = audit_path.with_name("audit.sha256")
    if not sha_path.exists():
        print(f"[ERROR] audit.sha256 not found at: {sha_path}")
        sys.exit(1)

    # 1. Verify audit file integrity
    actual_sha = sha256_file(audit_path)
    expected_sha = sha_path.read_text(encoding="utf-8").strip()
    if actual_sha != expected_sha:
        sys.exit("REFUSED: audit.json does not match audit.sha256")

    with open(audit_path, "r", encoding="utf-8") as f:
        audit = json.load(f)

    # 2. Verify config SHA matches current config
    current_cfg_sha = run_git(["hash-object", "strategy_config.yaml"])
    stored_cfg_sha = audit.get("strategy_config_sha", "")
    if stored_cfg_sha != current_cfg_sha:
        sys.exit(
            f"REFUSED: audit was generated for config {stored_cfg_sha[:8]}, "
            f"current config is {current_cfg_sha[:8]}. Re-run the backtest."
        )

    # 3. Verify clean tree at backtest time
    if not audit.get("working_tree_clean", False):
        sys.exit("REFUSED: audit was produced from a dirty working tree.")

    print("\n── Audit Ledger Validation ─────────────────────────────────────")
    g = cfg["gates"]
    metrics = audit.get("metrics", {})
    if not metrics:
        sys.exit("REFUSED: audit.json contains no window metrics.")

    # 4. Recompute gates independently
    for name, m in metrics.items():
        dd_ok = m.get("max_drawdown_pct", 99.0) < g["max_drawdown_pct"]
        alpha_ok = m.get("alpha_after_tax_pct", -99.0) >= g["min_alpha_after_tax_pct"]
        exp_ok = m.get("expectancy_r", -9.0) >= g["min_expectancy_r"]
        pf_ok = m.get("profit_factor", 0.0) >= g["min_profit_factor"]
        trades_ok = m.get("n_trades", 0) >= g["min_trades"]
        comp_ok = bool(m.get("compliance_applied", False))

        print(f"  Window [{name}]:")
        print(f"    Drawdown < {g['max_drawdown_pct']}%:       {m.get('max_drawdown_pct', 'N/A')}% {'✓' if dd_ok else '✗'}")
        print(f"    Alpha >= {g['min_alpha_after_tax_pct']}%:         {m.get('alpha_after_tax_pct', 'N/A')}% {'✓' if alpha_ok else '✗'}")
        print(f"    Expectancy >= {g['min_expectancy_r']}R:    {m.get('expectancy_r', 'N/A')}R {'✓' if exp_ok else '✗'}")
        print(f"    Profit Factor >= {g['min_profit_factor']}: {m.get('profit_factor', 'N/A')} {'✓' if pf_ok else '✗'}")
        print(f"    Trades >= {g['min_trades']}:         {m.get('n_trades', 'N/A')} {'✓' if trades_ok else '✗'}")
        print(f"    Compliance Applied:      {'✓' if comp_ok else '✗'}")

        if not (dd_ok and alpha_ok and exp_ok and pf_ok and trades_ok and comp_ok):
            sys.exit(f"REFUSED: window {name} does not meet the gates.")

    print("\n[OK] All gates passed successfully.")
    return audit


def check_clean_tree() -> None:
    """Ensure git working tree is clean. Exits if dirty."""
    status = run_git(["status", "--porcelain"])
    if status:
        print("[ERROR] Git working tree has uncommitted changes:")
        print(status)
        print("\n  → Commit or stash all changes before authorizing.")
        sys.exit(1)
    print("[OK] Working tree is clean.")


def main():
    parser = argparse.ArgumentParser(
        description="Authorize FInsight for trading after passing backtest gates."
    )
    parser.add_argument(
        "--confirm-ledger",
        required=True,
        metavar="PATH",
        help="Path to the audit.json generated by backtest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only — do not write authorized_deployment.json or commit.",
    )
    args = parser.parse_args()

    cfg = load_config()
    mode = current_mode(cfg)
    audit_path = Path(args.confirm_ledger)

    print("\n╔══════════════════════════════════════════════════════════════╗")
    print(f"║     FInsight Trading Engine — Deployment Authorization [{mode}] ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    # Mode validation: LIVE mode strictly requires paper results
    if mode == "LIVE":
        paper_result_file = BASE_DIR / "docs" / "PAPER_RESULT.json"
        if not paper_result_file.exists():
            sys.exit(
                "REFUSED: LIVE deployment requires docs/PAPER_RESULT.json verifying paper trading criteria. "
                f"File not found at: {paper_result_file}"
            )
        try:
            with open(paper_result_file, "r", encoding="utf-8") as pf:
                paper_res = json.load(pf)
            if not paper_res.get("passed", False):
                sys.exit("REFUSED: docs/PAPER_RESULT.json indicates paper trading criteria NOT met.")
        except Exception as exc:
            sys.exit(f"REFUSED: unable to read docs/PAPER_RESULT.json: {exc}")

    # Step 1: Validate audit.json
    audit = validate_audit(audit_path, cfg)

    # Step 2: Check clean working tree
    check_clean_tree()

    # Step 3: Get current HEAD SHA and config SHA
    sha = run_git(["rev-parse", "HEAD"])
    cfg_sha = run_git(["hash-object", "strategy_config.yaml"])
    audit_sha = sha256_file(audit_path)
    short_sha = sha[:8]
    print(f"[OK] Current HEAD SHA: {sha}")

    if args.dry_run:
        print("\n[DRY RUN] Validation passed. No files written (--dry-run mode).")
        sys.exit(0)

    # Step 4: Write authorized_deployment.json
    deployment_info = {
        "authorized_at": datetime.now().isoformat(),
        "authorized_sha": sha,
        "mode": mode,
        "strategy_config_sha": cfg_sha,
        "audit_sha256": audit_sha,
        "audit_generated_at": audit.get("audit_generated_at", audit.get("generated_at", "unknown")),
        "dual_gate_summary": audit.get("dual_gate", {}),
        "note": (
            f"This file authorizes the engine in {mode} mode. "
            "Any code or config change after this will break the SHA lock. "
            "Re-run authorize_live.py after any change."
        ),
    }

    with open(AUTHORIZED_FILE, "w", encoding="utf-8") as f:
        json.dump(deployment_info, f, indent=2)

    print(f"[OK] authorized_deployment.json written.")

    # Step 5: Stage and commit
    run_git(["add", "authorized_deployment.json"])
    run_git(["commit", "-m", f"chore: authorize {mode.lower()} deployment [{short_sha}]"])

    print(f"\n╔══════════════════════════════════════════════════════════════╗")
    print(f"║  ✓  AUTHORIZATION COMPLETE ({mode})                             ║")
    print(f"║     SHA: {sha[:8]}                                            ║")
    print(f"╚══════════════════════════════════════════════════════════════╝\n")
    print(f"The engine is now authorized in {mode} mode. Start it with:")
    print("    python -m live_runner.main")
    print("\nWARNING: Any code or config change will break the lock. Re-authorize after each change.")


if __name__ == "__main__":
    main()
