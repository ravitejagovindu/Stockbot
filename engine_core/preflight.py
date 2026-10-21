"""engine_core/preflight.py — Pre-flight data and adjustment spot-checks.

Runs before nightly pipeline / paper runs to guarantee point-in-time corporate action
adjustments and critical data components match deterministic ground-truth values.
"""
from __future__ import annotations

import logging
from datetime import date
import pandas as pd

from engine_core.adjustments import get_adjusted_series
from engine_core.sector_map import sector_for

logger = logging.getLogger(__name__)


def assert_preflight_spot_check() -> bool:
    """Spot-check corporate action adjustment on a known test case.

    Verifies that:
    1. A 1:2 split adjusts historical bars prior to ex-date by 0.5.
    2. Bars on or after ex-date remain unadjusted (factor 1.0).
    3. Future corporate actions after as_of_date are ignored.
    4. Sector map loads successfully.

    Raises RuntimeError on any mismatch.
    """
    dates = [
        date(2024, 5, 29),
        date(2024, 5, 30),
        date(2024, 5, 31),
        date(2024, 6, 3),
    ]
    raw_df = pd.DataFrame(
        {
            "open_raw": [200.0, 200.0, 100.0, 100.0],
            "high_raw": [205.0, 205.0, 105.0, 105.0],
            "low_raw": [195.0, 195.0, 95.0, 95.0],
            "close_raw": [200.0, 200.0, 100.0, 100.0],
        },
        index=dates,
    )
    split_action = {
        "ex_date": date(2024, 5, 31),
        "action_type": "SPLIT",
        "ratio_numerator": 1.0,
        "ratio_denominator": 2.0,
    }

    # Evaluate as of 2024-06-03 (after split)
    adj = get_adjusted_series(raw_df, [split_action], as_of_date=date(2024, 6, 3))
    expected_closes = [100.0, 100.0, 100.0, 100.0]
    actual_closes = list(adj["close_adj"])
    for i, (act, exp) in enumerate(zip(actual_closes, expected_closes)):
        if abs(act - exp) > 1e-6:
            raise RuntimeError(
                f"PREFLIGHT_SPOT_CHECK_FAILED: bar {dates[i]} expected close {exp}, got {act}"
            )

    # Evaluate as of 2024-05-30 (before split is known/effective)
    adj_past = get_adjusted_series(raw_df, [split_action], as_of_date=date(2024, 5, 30))
    expected_past = [200.0, 200.0, 100.0, 100.0]
    actual_past = list(adj_past["close_adj"])
    for i, (act, exp) in enumerate(zip(actual_past, expected_past)):
        if abs(act - exp) > 1e-6:
            raise RuntimeError(
                f"PREFLIGHT_SPOT_CHECK_FAILED: point-in-time bar {dates[i]} expected close {exp}, got {act}"
            )

    # Verify sector map works
    sec = sector_for("TCS")
    if not sec or not isinstance(sec, str):
        raise RuntimeError("PREFLIGHT_SPOT_CHECK_FAILED: sector_map failed to load")

    logger.info("[PREFLIGHT] ✓ Corporate action adjustment and sector map spot-checks passed.")
    return True
