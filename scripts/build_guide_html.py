"""Thin command-line wrapper: the logic lives in stockbot.data_checks.guide_html. Run from anywhere: py scripts/build_guide_html.py [--stamp] [--data P] [--template P] [--out P]. Offline; touches no database."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.data_checks.guide_html", run_name="__main__", alter_sys=True)
