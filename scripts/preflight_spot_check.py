"""Thin command-line wrapper: the logic lives in stockbot.data_checks.preflight_spot_check (restructure Phase 8). Run from anywhere: py scripts/preflight_spot_check.py [args]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.data_checks.preflight_spot_check", run_name="__main__", alter_sys=True)
