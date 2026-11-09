"""tests/unit/test_regulatory_barrier.py — SEBI Click-to-Trade regulatory barrier enforcement."""
from __future__ import annotations

import pathlib
import re
from stockbot.live.main import app

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
    """Everything under stockbot/ and scripts/ is scanned. The broker-data client name (kiteconnect) is allowed ONLY in the ingestion package, which uses it to fetch prices;
    order placement / UI-automation terms are forbidden everywhere."""
    root = pathlib.Path(__file__).resolve().parents[2]
    orders_only = re.compile(r"place_order|modify_order|selenium|playwright|pyautogui|pywinauto", re.I)
    hits = []
    for d in ("stockbot", "scripts"):
        for p in (root / d).rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            rx = orders_only if "stockbot/data/ingestion" in p.as_posix() else FORBIDDEN_CODE
            if rx.search(text):
                hits.append(str(p))
    assert not hits, f"broker/order automation code found: {hits}"
