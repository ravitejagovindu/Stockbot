"""F10 - a backtest must not use the network: the guard raises (the runner is wrapped by it: tests/unit/test_engine_backtest.py) and no backtest module imports a network library."""
from __future__ import annotations

import ast
import socket
import urllib.request
from pathlib import Path

import pytest

from stockbot.backtest.no_network import NetworkAccessError, network_forbidden

ROOT = Path(__file__).resolve().parents[2]


def test_the_guard_blocks_sockets_dns_urllib_and_requests_and_is_restored_afterwards():
    import requests
    original = socket.create_connection
    with network_forbidden():
        with pytest.raises(NetworkAccessError):
            socket.create_connection(("127.0.0.1", 9))
        with pytest.raises(NetworkAccessError):
            socket.getaddrinfo("example.com", 80)
        with pytest.raises(NetworkAccessError):
            urllib.request.urlopen("http://127.0.0.1:9/")
        with pytest.raises(Exception) as ei:
            requests.get("http://127.0.0.1:9/", timeout=1)
        assert "network access attempted" in str(ei.value) or isinstance(ei.value, NetworkAccessError) or "NetworkAccessError" in repr(ei.value)
    assert socket.create_connection is original


def test_no_backtest_module_imports_a_network_library():
    banned = {"requests", "urllib", "urllib3", "httpx", "yfinance", "aiohttp"}
    for p in (ROOT / "stockbot" / "backtest").glob("*.py"):
        mods = set()
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])
        assert not (mods & banned), (p.name, mods & banned)
