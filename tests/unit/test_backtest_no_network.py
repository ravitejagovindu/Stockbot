"""F10 — a backtest must not use the network: the guard raises, the Simulator is wrapped by it, and the runner no longer scrapes."""
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


def test_a_network_call_inside_simulator_run_raises(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import backtest.simulator as simmod
    from config import load_config
    from data.db.connection import Base
    from tests.fixtures import mini_lake

    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    ds = mini_lake.build(s)

    def fetch_from_nse(*a, **k):                                   # what the old on-demand fetch looked like
        return urllib.request.urlopen("http://127.0.0.1:9/api/corporates-corporateActions?index=equities&symbol=X", timeout=2)   # local closed port: never leaves the machine

    monkeypatch.setattr(simmod, "build_candidate_dicts", fetch_from_nse)
    with pytest.raises(NetworkAccessError):
        simmod.Simulator(load_config(), s).run(ds[290], ds[295], 1_000_000.0)


def test_run_backtest_no_longer_scrapes_or_imports_the_scrapers():
    src = (ROOT / "backtest" / "run_backtest.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any("bifurcated_scraper" in (m or "") for m in imported)
    assert "--scrape" not in src and "args.scrape" not in src


def test_no_backtest_module_imports_a_network_library():
    banned = {"requests", "urllib", "urllib3", "httpx", "yfinance", "aiohttp"}
    for p in (ROOT / "backtest").glob("*.py"):
        mods = set()
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])
        assert not (mods & banned), (p.name, mods & banned)
