"""
FInsight Trading Engine — Git-SHA Deployment Lock

Prevents the live EOD runner from executing if the codebase has been modified
since the last authorized_live.py run. This is a core safety mechanism.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

AUTHORIZED_DEPLOYMENT_FILE = Path(__file__).resolve().parents[1] / "authorized_deployment.json"


def _run_git(args: list[str]) -> str:
    """Run a git command and return stdout. Raises SystemExit on failure."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent,
    )
    if result.returncode != 0:
        print(f"[GIT-LOCK] git command failed: git {' '.join(args)}")
        print(f"[GIT-LOCK] stderr: {result.stderr}")
        sys.exit("SYSTEM_LOCKED_GIT_ERROR")
    return result.stdout.strip()


def get_current_sha() -> str:
    """Returns the current HEAD commit SHA."""
    return _run_git(["rev-parse", "HEAD"])


def has_clean_working_tree() -> bool:
    """Returns True if git working tree is clean (no uncommitted changes)."""
    status = _run_git(["status", "--porcelain"])
    return status == ""


def verify_git_lock() -> None:
    """
    Called at FastAPI startup. Enforces the deployment lock.

    Raises SystemExit if:
    - authorized_deployment.json doesn't exist (not yet authorized)
    - Working tree is dirty (uncommitted changes)
    - Current HEAD SHA doesn't match the authorized SHA

    On success: logs the verified SHA and returns.
    """
    # 1. Check authorized_deployment.json exists
    if not AUTHORIZED_DEPLOYMENT_FILE.exists():
        sys.exit(
            "SYSTEM_NOT_AUTHORIZED: authorized_deployment.json not found. "
            "Run 'python authorize_live.py --confirm-ledger=backtest/outputs/audit.json' first."
        )

    # 2. Load authorized deployment info
    with open(AUTHORIZED_DEPLOYMENT_FILE, "r", encoding="utf-8") as f:
        authorized = json.load(f)

    authorized_sha = authorized.get("authorized_sha")
    if not authorized_sha:
        sys.exit("SYSTEM_LOCKED_CORRUPT_AUTH_FILE: authorized_sha missing from authorized_deployment.json")

    # 3. Check clean working tree
    if not has_clean_working_tree():
        sys.exit(
            "SYSTEM_LOCKED_DIRTY_TREE: Uncommitted changes detected. "
            "Commit all changes or stash them before running the live engine."
        )

    # 4. Check current SHA matches authorized SHA
    current_sha = get_current_sha()
    if current_sha != authorized_sha:
        sys.exit(
            f"SYSTEM_LOCKED_CODE_MODIFIED: "
            f"Current HEAD ({current_sha[:8]}) does not match "
            f"authorized SHA ({authorized_sha[:8]}). "
            f"Re-run 'python authorize_live.py' to re-authorize."
        )

    print(f"[GIT-LOCK] ✓ Deployment lock verified. Running authorized commit: {current_sha[:8]}")
    print(f"[GIT-LOCK] ✓ Authorized at: {authorized.get('authorized_at', 'unknown')}")


def read_authorized_info() -> dict:
    """
    Returns the authorized deployment info without enforcing the lock.
    Used by the API to display system status.
    """
    if not AUTHORIZED_DEPLOYMENT_FILE.exists():
        return {"authorized": False}
    with open(AUTHORIZED_DEPLOYMENT_FILE, "r", encoding="utf-8") as f:
        info = json.load(f)
    info["authorized"] = True
    info["current_sha"] = get_current_sha()
    info["sha_matches"] = info["current_sha"] == info.get("authorized_sha")
    info["tree_clean"] = has_clean_working_tree()
    return info
