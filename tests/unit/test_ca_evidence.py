"""F2 Step 4: evidence tiers for split/bonus events (strong = Yahoo factor within 3%; weak = raw close ratio within 25% AND closer
to the logged factor than to any other standard ratio; otherwise unsupported -> stored as OTHER)."""
from __future__ import annotations

import pytest

from data.ingestion.ca_evidence import STANDARD_RATIOS, classify, nearest_standard, best_pair


def test_strong_when_yahoo_factor_within_3pct():
    assert classify(0.5, raw_ratio=0.9, yahoo_factor=0.51)[0] == "STRONG"
    assert classify(0.5, raw_ratio=0.9, yahoo_factor=0.53)[0] != "STRONG"


def test_weak_when_raw_ratio_is_close_and_nearest():
    assert classify(0.2, raw_ratio=0.21, yahoo_factor=None)[0] == "WEAK"
    # 0.224 is as close to 0.25 (a 3:1 bonus) as to 0.2 (a 5:1 split): ambiguous, so not accepted on price alone (MARINE)
    assert classify(0.2, raw_ratio=0.224, yahoo_factor=None)[0] == "UNSUPPORTED"
    assert classify(0.5, raw_ratio=0.52, yahoo_factor=None)[0] == "WEAK"


def test_one_to_one_bonus_is_not_confused_with_one_to_two():
    # logged 1:1 bonus (0.5) but the price fell to 0.6 -> nearer to the 1:2 factor (0.667): unsupported
    assert classify(0.5, raw_ratio=0.6, yahoo_factor=None)[0] == "UNSUPPORTED"
    # logged 1:2 bonus (0.667) but the price halved -> unsupported
    assert classify(2 / 3, raw_ratio=0.5, yahoo_factor=None)[0] == "UNSUPPORTED"
    assert classify(2 / 3, raw_ratio=0.68, yahoo_factor=None)[0] == "WEAK"


def test_no_price_step_is_unsupported_and_missing_data_is_flagged():
    assert classify(0.5, raw_ratio=0.935, yahoo_factor=None)[0] == "UNSUPPORTED"     # DVL-like: -6.5% for a 1:2 bonus
    t, why = classify(0.5, raw_ratio=None, yahoo_factor=None)
    assert t == "UNSUPPORTED" and "no price" in why.lower()


def test_nearest_standard_includes_the_logged_factor():
    assert nearest_standard(0.12, 0.1) == 0.1
    assert 0.5 in STANDARD_RATIOS and 1.0 in STANDARD_RATIOS


def test_best_pair_searches_two_sessions_either_side():
    dates = ["d0", "d1", "d2", "d3", "d4", "d5", "d6"]
    close = [100, 100, 100, 100, 50, 50, 50]            # the step is on d4 (offset +1 if the ex-date is d3)
    r, off = best_pair(dates, close, ex_index=3, f=0.5)
    assert off == 1 and r == pytest.approx(0.5)
    close2 = [100, 100, 100, 100, 100, 100, 50]         # step 3 sessions after the ex-date: outside the window
    r2, off2 = best_pair(dates, close2, ex_index=3, f=0.5)
    assert abs(r2 - 0.5) > 0.4
