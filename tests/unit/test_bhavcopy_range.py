"""F2 — Bhavcopy range ingester: both layouts parse to the same staging schema (EQ only, ISIN + previous close kept)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scripts.ingest_raw_bhavcopy_range import candidate_urls, parse_bhavcopy


def test_legacy_layout():
    df = pd.DataFrame({
        "SYMBOL": ["RELIANCE", "FOO", "RELIANCE"], "SERIES": ["EQ", "BE", "N1"], "OPEN": [1512.0, 5, 6],
        "HIGH": [1540.95, 5, 6], "LOW": [1512.0, 5, 6], "CLOSE": [1535.3, 5, 6], "LAST": [1534.1, 5, 6],
        "PREVCLOSE": [1509.6, 5, 6], "TOTTRDQTY": [8096561, 1, 1], "ISIN": ["INE002A01018", "X", "Y"],
    })
    out = parse_bhavcopy(df, date(2020, 1, 2), "legacy")
    assert list(out["symbol"]) == ["RELIANCE"]
    r = out.iloc[0]
    assert (r.open_raw, r.close_raw, r.prev_close, r.volume_raw, r["isin"]) == (1512.0, 1535.3, 1509.6, 8096561, "INE002A01018")
    assert r.trade_date == "2020-01-02"


def test_udiff_layout():
    df = pd.DataFrame({
        "TckrSymb": ["RELIANCE", "FOO"], "SctySrs": ["EQ", "SM"], "OpnPric": [1182.0, 1], "HghPric": [1196.5, 1],
        "LwPric": [1181.7, 1], "ClsPric": [1187.0, 1], "PrvsClsgPric": [1180.0, 1], "TtlTradgVol": [100, 1],
        "ISIN": ["INE002A01018", "Z"],
    })
    out = parse_bhavcopy(df, date(2026, 9, 30))
    assert len(out) == 1 and out.iloc[0].prev_close == 1180.0 and out.iloc[0].close_raw == 1187.0


def test_unknown_layout_raises():
    with pytest.raises(ValueError):
        parse_bhavcopy(pd.DataFrame({"a": [1]}), date(2020, 1, 2))


def test_url_order_depends_on_era():
    assert "cm02JAN2020bhav" in candidate_urls(date(2020, 1, 2))[0]
    assert "BhavCopy_NSE_CM_0_0_0_20260930" in candidate_urls(date(2026, 9, 30))[0]


# ---- F2 fix: the file's own date must equal the requested date (NSE serves the previous session's
# sec_bhavdata_full file with HTTP 200 on holidays; the old code stamped the requested date on it).
class _Resp:
    def __init__(self, status, text="", content=b""):
        self.status_code, self.text, self.content = status, text, content or text.encode()


class _FakeSession:
    """404 for every archive URL except the 'full' file, which returns the given text."""
    def __init__(self, full_text):
        self.full_text = full_text
        self.headers = {}

    def get(self, url, timeout=30):
        if "sec_bhavdata_full" in url:
            return _Resp(200, self.full_text)
        return _Resp(404, "x" * 300)


def _full_csv(date1: str) -> str:
    pad = " " * 40
    return ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, "
            "TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
            f"RELIANCE, EQ, {date1}, 1509.6, 1512.0, 1540.9, 1512.0, 1534.1, 1535.3, 1530.0, 8096561, 1000.0, 5, 1, 1.0\n"
            + pad + "\n")


def test_holiday_served_with_previous_session_file_is_not_accepted():
    from scripts.ingest_raw_bhavcopy_range import fetch_day
    df, status, info = fetch_day(_FakeSession(_full_csv("01-Oct-2019")), date(2019, 10, 2))  # file says 1 Oct, asked 2 Oct
    assert df is None and status == "HOLIDAY_OR_MISSING"


def test_file_whose_date_matches_is_accepted():
    from scripts.ingest_raw_bhavcopy_range import fetch_day
    df, status, info = fetch_day(_FakeSession(_full_csv("02-Oct-2019")), date(2019, 10, 2))
    assert status == "OK" and list(df["trade_date"].unique()) == ["2019-10-02"]


def test_extract_file_date_all_layouts():
    from scripts.ingest_raw_bhavcopy_range import extract_file_date
    assert extract_file_date(pd.DataFrame({"DATE1": [" 01-Oct-2019"]})) == date(2019, 10, 1)
    assert extract_file_date(pd.DataFrame({"TIMESTAMP": ["02-JAN-2020"]})) == date(2020, 1, 2)
    assert extract_file_date(pd.DataFrame({"TradDt": ["2026-09-30"]})) == date(2026, 9, 30)
    assert extract_file_date(pd.DataFrame({"x": [1]})) is None
