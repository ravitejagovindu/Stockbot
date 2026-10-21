"""tests/unit/test_phase4_lock.py — Unit tests for Phase 4 deployment authorization and git lock."""
from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import pytest

from authorize_live import validate_audit
import live_runner.git_lock as git_lock


def test_validate_audit_rejects_dirty_tree(tmp_path):
    cfg = {
        "gates": {
            "max_drawdown_pct": 15.0,
            "min_alpha_after_tax_pct": -2.0,
            "min_expectancy_r": 0.15,
            "min_profit_factor": 1.3,
            "min_trades": 10,
        }
    }
    audit = {
        "strategy_config_sha": "abc12345",
        "working_tree_clean": False,
        "metrics": {
            "w1": {
                "max_drawdown_pct": 10.0,
                "alpha_after_tax_pct": 5.0,
                "expectancy_r": 0.25,
                "profit_factor": 1.5,
                "n_trades": 50,
                "compliance_applied": True,
            }
        },
    }
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps(audit), encoding="utf-8")
    sha_file = tmp_path / "audit.sha256"
    sha_file.write_text(hashlib.sha256(audit_file.read_bytes()).hexdigest(), encoding="utf-8")

    with patch("authorize_live.run_git", return_value="abc12345"):
        with pytest.raises(SystemExit, match="dirty working tree"):
            validate_audit(audit_file, cfg)


def test_validate_audit_rejects_config_hash_mismatch(tmp_path):
    cfg = {"gates": {}}
    audit = {
        "strategy_config_sha": "abc12345",
        "working_tree_clean": True,
        "metrics": {},
    }
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps(audit), encoding="utf-8")
    sha_file = tmp_path / "audit.sha256"
    sha_file.write_text(hashlib.sha256(audit_file.read_bytes()).hexdigest(), encoding="utf-8")

    with patch("authorize_live.run_git", return_value="diff_cfg_hash"):
        with pytest.raises(SystemExit, match="audit was generated for config"):
            validate_audit(audit_file, cfg)


def test_validate_audit_rejects_tampered_audit_file(tmp_path):
    cfg = {"gates": {}}
    audit = {"strategy_config_sha": "abc"}
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps(audit), encoding="utf-8")
    sha_file = tmp_path / "audit.sha256"
    sha_file.write_text("bogus_sha256", encoding="utf-8")

    with pytest.raises(SystemExit, match="does not match audit.sha256"):
        validate_audit(audit_file, cfg)


def test_validate_audit_recomputes_and_rejects_gate_failure(tmp_path):
    cfg = {
        "gates": {
            "max_drawdown_pct": 15.0,
            "min_alpha_after_tax_pct": -2.0,
            "min_expectancy_r": 0.15,
            "min_profit_factor": 1.3,
            "min_trades": 10,
        }
    }
    # Window w1 fails alpha gate (-5.0 < -2.0)
    audit = {
        "strategy_config_sha": "abc12345",
        "working_tree_clean": True,
        "metrics": {
            "w1": {
                "max_drawdown_pct": 10.0,
                "alpha_after_tax_pct": -5.0,  # FAIL
                "expectancy_r": 0.25,
                "profit_factor": 1.5,
                "n_trades": 50,
                "compliance_applied": True,
            }
        },
    }
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps(audit), encoding="utf-8")
    sha_file = tmp_path / "audit.sha256"
    sha_file.write_text(hashlib.sha256(audit_file.read_bytes()).hexdigest(), encoding="utf-8")

    with patch("authorize_live.run_git", return_value="abc12345"):
        with pytest.raises(SystemExit, match="window w1 does not meet the gates"):
            validate_audit(audit_file, cfg)


def test_git_lock_detects_modified_code(tmp_path):
    auth_file = tmp_path / "authorized_deployment.json"
    auth_file.write_text(json.dumps({
        "authorized_sha": "commit_111",
        "strategy_config_sha": "config_aaa",
        "mode": "PAPER",
    }), encoding="utf-8")

    with patch.object(git_lock, "AUTHORIZED_DEPLOYMENT_FILE", auth_file), \
         patch.object(git_lock, "has_clean_working_tree", return_value=True), \
         patch.object(git_lock, "get_current_sha", return_value="commit_222"), \
         patch.object(git_lock, "_run_git", side_effect=lambda a: "commit_other" if "HEAD~1" in a else "config_aaa"):
        with pytest.raises(SystemExit, match="SYSTEM_LOCKED_CODE_MODIFIED"):
            git_lock.verify_git_lock()


def test_git_lock_detects_modified_config(tmp_path):
    auth_file = tmp_path / "authorized_deployment.json"
    auth_file.write_text(json.dumps({
        "authorized_sha": "commit_111",
        "strategy_config_sha": "config_aaa",
        "mode": "PAPER",
    }), encoding="utf-8")

    with patch.object(git_lock, "AUTHORIZED_DEPLOYMENT_FILE", auth_file), \
         patch.object(git_lock, "has_clean_working_tree", return_value=True), \
         patch.object(git_lock, "get_current_sha", return_value="commit_111"), \
         patch.object(git_lock, "_run_git", return_value="config_MODIFIED"):
        with pytest.raises(SystemExit, match="SYSTEM_LOCKED_CONFIG_MODIFIED"):
            git_lock.verify_git_lock()


def test_git_lock_allows_auth_file_commit_on_top(tmp_path):
    auth_file = tmp_path / "authorized_deployment.json"
    auth_file.write_text(json.dumps({
        "authorized_sha": "commit_111",
        "strategy_config_sha": "config_aaa",
        "mode": "PAPER",
    }), encoding="utf-8")

    with patch.object(git_lock, "AUTHORIZED_DEPLOYMENT_FILE", auth_file), \
         patch.object(git_lock, "has_clean_working_tree", return_value=True), \
         patch.object(git_lock, "get_current_sha", return_value="commit_auth_commit"), \
         patch.object(git_lock, "_run_git", side_effect=lambda a: "commit_111" if "HEAD~1" in a else ("config_aaa" if "hash-object" in a else "authorized_deployment.json")), \
         patch.object(git_lock, "_only_auth_file_changed", return_value=True):
        # Should not raise
        git_lock.verify_git_lock()
