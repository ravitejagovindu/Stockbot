"""Thin command-line wrapper: the logic lives in stockbot.data_checks.data_catalogue (guides task). Run from anywhere: py scripts/gen_data_catalogue.py [--out PATH] [--no-coverage]. Read-only on the database."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_module("stockbot.data_checks.data_catalogue", run_name="__main__", alter_sys=True)
