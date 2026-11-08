"""stockbot/data_checks/preflight_spot_check.py — CLI Runner for Pre-flight Data & Adjustment Spot-Checks."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

from stockbot.data_checks.preflight import assert_preflight_spot_check


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").strip().partition(chr(10))[0])
    args = ap.parse_args()
    try:
        assert_preflight_spot_check()
        print("OK: Pre-flight spot-checks passed.")
        return 0
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
