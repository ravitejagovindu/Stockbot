"""Thin command-line wrapper: the logic lives in stockbot.validation.validate_max_t (restructure Phase 7). Run from anywhere: py scripts/validate_max_t.py [args]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.validation.validate_max_t", run_name="__main__", alter_sys=True)
