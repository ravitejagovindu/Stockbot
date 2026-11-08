"""One entry point for the golden checks (restructure Phase 8): ``py scripts/check_all.py [--data] [--final]``.

Steps (each is a pytest run in its own process; the exit code is the OR of all steps):
  G1  unit suite                    tests/unit and tests/fixtures-based tests (the default ``pytest tests`` run)
  G3  fixture baseline              the hand-derived trade on the fixture lake (tests/unit/test_baseline_reproducibility.py)
  G5  import boundaries             tests/unit/test_import_boundaries.py (fails on seeded violations, passes on the real tree)
  G6  parity / lookahead / idempotency / determinism / isolation / baseline reuse / strict mode   tests/unit/test_engine_*.py
  G2  env-gated real-database tests only with --data (STOCKBOT_DATA_TESTS=1; read-only on finsight.db)
--final adds STOCKBOT_FINAL_CHECK=1 (the allowlist-empty test of the boundary file, required at STOP 5).
G4 (finsight.db unchanged) is a hash / mtime check done by the reviewer's commands; it is printed here for reference only (size and mtime, no hashing of 3.4 GB).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
STEPS = (
    ("G1 unit suite", ["tests/unit", "-q"]),
    ("G3 fixture baseline", ["tests/unit/test_baseline_reproducibility.py", "-q"]),
    ("G5 import boundaries", ["tests/unit/test_import_boundaries.py", "tests/unit/test_every_module_imports_alone.py", "-q"]),
    ("G6 engine: parity, lookahead, idempotency, determinism, isolation, baseline reuse, strict mode",
     ["tests/unit/test_engine_decide.py", "tests/unit/test_engine_live.py", "tests/unit/test_engine_backtest.py", "tests/unit/test_engine_corporate.py",
      "tests/unit/test_engine_types.py", "tests/unit/test_risk_arbitration.py", "-q"]),
)
DATA_STEP = ("G2 real-database tests (read-only)", ["tests/data_integrity", "-q"])


def run_pytest(args: Sequence[str], env: dict) -> int:
    return subprocess.run([sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider"], cwd=ROOT, env=env).returncode


def run(*, data: bool = False, final: bool = False, runner: Optional[Callable[[Sequence[str], dict], int]] = None, out=print) -> int:
    runner = runner or run_pytest
    env = dict(os.environ)
    if data:
        env["STOCKBOT_DATA_TESTS"] = "1"
    if final:
        env["STOCKBOT_FINAL_CHECK"] = "1"
    steps = list(STEPS) + ([DATA_STEP] if data else [])
    results = []
    for name, args in steps:
        t0 = time.time()
        code = runner(args, env)
        results.append((name, code, time.time() - t0))
    db = ROOT / "finsight.db"
    out("")
    for name, code, secs in results:
        out(f"  {'PASS' if code == 0 else 'FAIL'}  {name}  ({secs:.0f}s)")
    if db.exists():
        st = db.stat()
        out(f"  G4   finsight.db size {st.st_size} mtime_ns {st.st_mtime_ns} (compare with docs/restructure/BASELINE.md; the sha256 is checked by the reviewer)")
    bad = [n for n, c, _ in results if c != 0]
    out("ALL CHECKS PASSED" if not bad else f"FAILED: {', '.join(bad)}")
    return 1 if bad else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", action="store_true", help="also run the env-gated real-database tests (G2)")
    ap.add_argument("--final", action="store_true", help="STOP-5 mode: the legacy allowlists must be empty")
    a = ap.parse_args(argv)
    return run(data=a.data, final=a.final)


if __name__ == "__main__":
    sys.exit(main())
