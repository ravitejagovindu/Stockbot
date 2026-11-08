"""Thin command-line wrapper: the logic lives in stockbot.data.ingestion.merge_asm_gsm_snapshots (restructure Phase 8). Run from anywhere: py scripts/merge_asm_gsm_snapshots.py [args]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.data.ingestion.merge_asm_gsm_snapshots", run_name="__main__", alter_sys=True)
