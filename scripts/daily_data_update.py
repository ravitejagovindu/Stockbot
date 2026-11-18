"""Thin command-line wrapper: the logic lives in stockbot.data.ingestion.daily_update. Run: py -3 scripts/daily_data_update.py [--scheduled] [--catch-up-only] [--plan] [--through YYYY-MM-DD]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.data.ingestion.daily_update", run_name="__main__", alter_sys=True)
