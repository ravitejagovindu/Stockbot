"""Thin command-line wrapper: the logic lives in stockbot.data.ingestion.ingest_raw_bhavcopy_range (restructure Phase 8). Run from anywhere: py scripts/ingest_raw_bhavcopy_range.py [args]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.data.ingestion.ingest_raw_bhavcopy_range", run_name="__main__", alter_sys=True)
