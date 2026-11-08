"""Thin command-line wrapper: the logic lives in stockbot.data.ingestion.f2_build_isin_symbol_map (restructure Phase 8). Run from anywhere: py scripts/f2_build_isin_symbol_map.py [args]."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.data.ingestion.f2_build_isin_symbol_map", run_name="__main__", alter_sys=True)
