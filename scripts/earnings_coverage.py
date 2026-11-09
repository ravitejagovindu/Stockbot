"""Thin command-line wrapper: the logic lives in stockbot.data_checks.earnings_coverage (restructure Phase 8). Run from anywhere: py scripts/earnings_coverage.py [args]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.data_checks.earnings_coverage", run_name="__main__", alter_sys=True)
