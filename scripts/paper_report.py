"""Thin command-line wrapper: the logic lives in stockbot.live.paper_report (restructure Phase 8). Run from anywhere: py scripts/paper_report.py [args]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.live.paper_report", run_name="__main__", alter_sys=True)
