"""F2b: point-in-time shares are the current issued size walked back through SPLIT/BONUS price factors."""
from datetime import date

import pytest

from data.ingestion.pit_shares import derive_segments, shares_on

EX = date(2024, 3, 1)


def test_split_one_to_ten_gives_a_tenth_of_the_shares_before_the_ex_date():
    seg = derive_segments(1_000_000, [(EX, 0.1)])
    assert shares_on(seg, date(2024, 2, 29)) == (100_000, 1) and shares_on(seg, EX) == (1_000_000, 1)


def test_bonus_one_to_one_halves_the_earlier_count_and_events_compound_back_in_time():
    seg = derive_segments(1_000_000, [(date(2024, 3, 1), 0.5), (date(2020, 6, 1), 0.2)])
    assert shares_on(seg, date(2022, 1, 3)) == (500_000, 1) and shares_on(seg, date(2019, 1, 1)) == (100_000, 1)


def test_two_events_on_one_date_multiply():
    seg = derive_segments(1_000_000, [(EX, 0.5), (EX, 0.2)])
    assert shares_on(seg, date(2024, 2, 1))[0] == 100_000


def test_market_cap_is_consistent_across_a_split_and_a_bonus_ex_date():
    """raw price x shares in force: the same company is worth the same on both sides of the ex-date (price drops by the factor, shares rise by 1/factor)."""
    for factor in (0.1, 0.5, 0.25):
        shares_now = 8_000_000
        seg = derive_segments(shares_now, [(EX, factor)])
        price_after = 100.0
        price_before = price_after / factor                      # raw price the day before the ex-date (no market move)
        mc_before = price_before * shares_on(seg, date(2024, 2, 29))[0]
        mc_after = price_after * shares_on(seg, EX)[0]
        assert mc_before == pytest.approx(mc_after, rel=1e-9)


def test_segments_before_an_unadjustable_event_are_unreliable_and_later_ones_reliable():
    seg = derive_segments(1_000_000, [(date(2024, 3, 1), 0.5)], last_unadjusted=date(2022, 5, 1))
    assert shares_on(seg, date(2021, 1, 1)) == (500_000, 0)
    assert shares_on(seg, date(2022, 5, 1)) == (500_000, 1) and shares_on(seg, date(2025, 1, 1)) == (1_000_000, 1)


def test_no_events_gives_a_flat_reliable_series_and_a_bad_factor_is_rejected():
    assert derive_segments(5, []) == [(date(2013, 1, 1), 5, 1)]
    with pytest.raises(ValueError):
        derive_segments(5, [(EX, 0.0)])


# ---- D1: rights walk-back, 45-day band, anchors ------------------------------------------------------------
from data.ingestion.pit_shares import parse_rights_ratio, rights_factor


def test_rights_ratio_parses_only_when_unambiguous():
    assert parse_rights_ratio("2:3 Rights 2:3@Prem Rs.345/-") == (2, 3)
    assert parse_rights_ratio("5:6 Dividend Re1/- Per Share + Rights Issue 5:6") == (5, 6)
    assert parse_rights_ratio("3:11 Rights-Eq3:11 & 1wrnt:1eq") == (3, 11)
    assert parse_rights_ratio("Rights 2:3 and 1:5") is None and parse_rights_ratio("Rights Issue") is None and parse_rights_ratio("") is None


def test_rights_shares_arrive_45_days_after_the_ex_date_and_the_band_is_unreliable():
    ex = date(2022, 6, 1)
    seg = derive_segments(1_300_000, [], rights=[(ex, rights_factor(3, 10))])      # 3 new for 10 held: 1,000,000 -> 1,300,000
    assert shares_on(seg, date(2022, 3, 1)) == (1_000_000, 1)
    assert shares_on(seg, date(2022, 5, 1)) == (1_000_000, 0)                      # inside [ex-45d, ex+45d)
    assert shares_on(seg, date(2022, 6, 20)) == (1_000_000, 0)
    assert shares_on(seg, date(2022, 7, 20)) == (1_300_000, 1)                     # after ex+45d


def test_an_anchor_in_the_past_walks_forward_and_back():
    seg = derive_segments(500_000, [(date(2021, 1, 1), 0.5)], anchor_date=date(2020, 6, 1))   # 500k held BEFORE a 1:1 bonus -> 1,000,000 after
    assert shares_on(seg, date(2019, 1, 1)) == (500_000, 1) and shares_on(seg, date(2022, 1, 1)) == (1_000_000, 1)


def test_unparseable_rights_style_events_still_make_earlier_segments_unreliable():
    seg = derive_segments(1_000_000, [], last_unadjusted=date(2021, 1, 1))
    assert shares_on(seg, date(2020, 1, 1))[1] == 0 and shares_on(seg, date(2021, 1, 1))[1] == 1
