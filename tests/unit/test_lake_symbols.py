"""stockbot.data.ingestion.lake_symbols.lake_symbol: ISIN -> canonical symbol resolution, hand-derived."""
import pandas as pd

from stockbot.data.ingestion.lake_symbols import lake_symbol

IMAP = pd.DataFrame([
    {"isin": "INE001", "canonical_symbol": "NEWCO", "first_date": "2015-01-01", "last_date": "2019-12-31"},
    {"isin": "INE001", "canonical_symbol": "NEWCO2", "first_date": "2020-01-01", "last_date": "2026-12-31"},
    {"isin": "INE002", "canonical_symbol": "OLDCO", "first_date": "2013-01-01", "last_date": "2016-12-31"},
])


def test_the_mapping_in_force_on_the_ex_date_wins():
    assert lake_symbol(IMAP, "INE001", "FEED", "2018-06-01") == "NEWCO"
    assert lake_symbol(IMAP, "INE001", "FEED", "2021-06-01") == "NEWCO2"


def test_outside_every_range_the_latest_mapping_is_used():
    assert lake_symbol(IMAP, "INE002", "FEED", "2020-01-01") == "OLDCO"            # after the last range: the last mapping of that ISIN
    assert lake_symbol(IMAP, "INE001", "FEED", "2010-01-01") == "NEWCO2"           # before the first range: still the latest known


def test_without_an_isin_or_a_mapping_the_feed_symbol_is_kept():
    assert lake_symbol(IMAP, None, "FEED", "2018-06-01") == "FEED"
    assert lake_symbol(IMAP, float("nan"), "FEED", "2018-06-01") == "FEED"
    assert lake_symbol(IMAP, "INE999", "FEED", "2018-06-01") == "FEED"
