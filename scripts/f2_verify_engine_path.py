"""Thin command-line wrapper: the logic lives in stockbot.data_checks.f2_verify_engine_path (restructure Phase 8). Run from anywhere: py scripts/f2_verify_engine_path.py [args]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.data_checks.f2_verify_engine_path", run_name="__main__", alter_sys=True)
