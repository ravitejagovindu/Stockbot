"""Thin command-line wrapper: the logic lives in stockbot.live.health_check (restructure Phase 10). Run from anywhere: py scripts/daily_health_check.py [--today D]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.live.health_check", run_name="__main__", alter_sys=True)
