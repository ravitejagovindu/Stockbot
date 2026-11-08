"""Thin command-line wrapper: the logic lives in stockbot.validation.f9_power_study (restructure Phase 7). Run from anywhere: py scripts/f9_power_study.py [args]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.validation.f9_power_study", run_name="__main__", alter_sys=True)
