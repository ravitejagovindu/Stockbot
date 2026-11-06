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
