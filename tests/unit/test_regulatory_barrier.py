"""tests/unit/test_regulatory_barrier.py — SEBI Click-to-Trade regulatory barrier enforcement."""
from __future__ import annotations

import pathlib
import re
from live_runner.main import app

FORBIDDEN_ROUTE = re.compile(r"order|place|execute|trade|buy|sell|broker|kite", re.I)
FORBIDDEN_CODE = re.compile(r"place_order|modify_order|kiteconnect|selenium|playwright|pyautogui|pywinauto", re.I)
ALLOWED = {"/positions/open", "/positions/close"}  # these only RECORD fills; they call no broker


def test_no_order_routes():
    bad = [
        r.path for r in app.routes
        if hasattr(r, "path") and r.path not in ALLOWED and FORBIDDEN_ROUTE.search(r.path)
    ]
    assert not bad, f"order-like routes found: {bad}"


def test_no_broker_order_code():
    root = pathlib.Path(__file__).resolve().parents[2]
    hits = [
        str(p) for d in ("live_runner", "engine_core") for p in (root / d).rglob("*.py")
        if FORBIDDEN_CODE.search(p.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not hits, f"broker/order automation code found: {hits}"
