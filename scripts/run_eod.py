"""Thin command-line wrapper: the logic lives in stockbot.live.eod_cli (restructure Phase 9). Run from anywhere: py scripts/run_eod.py [--date D] [--mode M]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.live.eod_cli", run_name="__main__", alter_sys=True)
