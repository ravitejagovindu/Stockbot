"""ADTV and market cap must use RAW prices only (engine invariant 2).  A source-level check over every call site, plus a behavioural check."""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd

from stockbot.data.adjustments import compute_adtv, compute_market_cap, get_adjusted_series

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"tests", ".git", "__pycache__", "venv", ".venv", "node_modules", "backtest/outputs_recomputed_net"}


def _call_sites(names):
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts) or rel == "stockbot/data/adjustments.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                if fn in names:
                    yield rel, node.lineno, fn, [ast.unparse(a) for a in node.args] + [ast.unparse(k.value) for k in node.keywords]


def _problems(fn, args):
    text = " ".join(args).lower()
    out = []
    if "adj" in text:
        out.append("adjusted input")
    if fn == "compute_adtv" and not all(("raw" in a.lower()) for a in args[:2]):
        out.append("close/volume arguments are not named raw")
    if fn == "compute_market_cap" and "raw" not in args[0].lower():
        out.append("price argument is not named raw")
    return out


def test_the_checker_flags_adjusted_inputs():
    assert _problems("compute_adtv", ["df['close_adj']", "df['volume_raw']"])
    assert _problems("compute_adtv", ["close", "volume"])
    assert _problems("compute_market_cap", ["adjusted_close", "shares"])
    assert not _problems("compute_adtv", ["raw_ohlcv['close_raw']", "raw_ohlcv['volume_raw']"])


def test_every_adtv_and_market_cap_call_site_uses_raw_inputs():
    sites = list(_call_sites({"compute_adtv", "compute_market_cap"}))
    assert sites, "no call sites found: the check would pass vacuously"
    bad = [(rel, line, fn, args, p) for rel, line, fn, args in sites for p in _problems(fn, args)]
    assert not bad, bad


def test_adjusted_frames_carry_no_volume_and_adtv_differs_from_an_adjusted_one():
    idx = pd.date_range("2024-01-01", periods=30, freq="B").date
    raw = pd.DataFrame({"open_raw": 100.0, "high_raw": 100.0, "low_raw": 100.0, "close_raw": 100.0, "volume_raw": 1000}, index=idx)
    raw.loc[raw.index[15:], ["open_raw", "high_raw", "low_raw", "close_raw"]] = 50.0                      # a 1:2 split on idx[15]
    adj = get_adjusted_series(raw, [{"ex_date": idx[15], "action_type": "SPLIT", "ratio_numerator": 1.0, "ratio_denominator": 2.0}], as_of_date=idx[-1])
    assert "volume_raw" not in adj.columns and not any("volume" in c for c in adj.columns)
    a_raw = compute_adtv(raw["close_raw"], raw["volume_raw"], 20).iloc[-1]
    a_adj = compute_adtv(adj["close_adj"], raw["volume_raw"], 20).iloc[-1]
    expected_raw = float((raw["close_raw"] * raw["volume_raw"]).iloc[-20:].mean())          # traded value actually seen: 5 bars at 100, 15 at 50
    assert np.isclose(a_raw, expected_raw) and np.isclose(expected_raw, 62_500.0)
    assert not np.isclose(a_raw, a_adj)                                                      # an adjusted ADTV would be 50,000: wrong
    assert compute_market_cap(50.0, 1_000_000) == 50.0 * 1_000_000
