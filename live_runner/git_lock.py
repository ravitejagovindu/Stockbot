"""FInsight Trading Engine — Git-SHA Deployment Lock.

Prevents the live EOD runner from executing if the codebase or strategy config
has been modified since the last authorized_live.py run. This is a core safety mechanism.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
AUTHORIZED_DEPLOYMENT_FILE = BASE_DIR / "authorized_deployment.json"


def _run_git(args: list[str]) -> str:
    """Run a git command and return stdout. Raises SystemExit on failure."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
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


def _only_auth_file_changed() -> bool:
    """Returns True if the only file changed in HEAD compared to HEAD~1 is authorized_deployment.json."""
    try:
        files = _run_git(["diff", "--name-only", "HEAD~1", "HEAD"]).split()
        return files == ["authorized_deployment.json"]
    except Exception:
        return False


def verify_git_lock() -> None:
    """Enforce the deployment lock.

    Raises SystemExit if:
    - authorized_deployment.json doesn't exist (not yet authorized)
    - Working tree is dirty (uncommitted changes)
    - Current commit is not authorized (or parent is authorized and only auth file was committed)
    - strategy_config.yaml hash doesn't match the authorized config hash
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

    # 4. Check current SHA matches authorized SHA (or parent if only authorized_deployment.json was committed)
    current_sha = get_current_sha()
    ok = (current_sha == authorized_sha)
    if not ok:
        try:
            parent_sha = _run_git(["rev-parse", "HEAD~1"])
            if parent_sha == authorized_sha and _only_auth_file_changed():
                ok = True
        except Exception:
            pass

    if not ok:
        sys.exit("SYSTEM_LOCKED_CODE_MODIFIED")

    # 5. Check strategy_config.yaml hash has not changed
    auth_config_sha = authorized.get("strategy_config_sha")
    current_config_sha = _run_git(["hash-object", "strategy_config.yaml"])
    if auth_config_sha and current_config_sha != auth_config_sha:
        sys.exit("SYSTEM_LOCKED_CONFIG_MODIFIED")

    print(f"[GIT-LOCK] ✓ Deployment lock verified. Running authorized commit: {current_sha[:8]}")
    print(f"[GIT-LOCK] ✓ Mode: {authorized.get('mode', 'UNKNOWN')}, Authorized at: {authorized.get('authorized_at', 'unknown')}")


def read_authorized_info() -> dict:
    """Return dictionary with authorization status for health check endpoint."""
    tree_clean = has_clean_working_tree()
    if not AUTHORIZED_DEPLOYMENT_FILE.exists():
        return {
            "authorized": False,
            "sha_matches": False,
            "tree_clean": tree_clean,
            "authorized_sha": None,
        }
    try:
        with open(AUTHORIZED_DEPLOYMENT_FILE, "r", encoding="utf-8") as f:
            authorized = json.load(f)
        auth_sha = authorized.get("authorized_sha")
        current_sha = get_current_sha()
        sha_matches = (current_sha == auth_sha)
        if not sha_matches:
            try:
                parent_sha = _run_git(["rev-parse", "HEAD~1"])
                if parent_sha == auth_sha and _only_auth_file_changed():
                    sha_matches = True
            except Exception:
                pass
        return {
            "authorized": True,
            "sha_matches": sha_matches,
            "tree_clean": tree_clean,
            "authorized_sha": auth_sha,
            "authorized_at": authorized.get("authorized_at"),
            "mode": authorized.get("mode"),
        }
    except Exception:
        return {
            "authorized": False,
            "sha_matches": False,
            "tree_clean": tree_clean,
            "authorized_sha": None,
        }
