"""Fixtures for the BFF tests: temporary files only, no network, never the real state or lake."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))      # tests/bff is a package under tests/, but the helper module is imported by its plain name

from bff.app import create_app  # noqa: E402
from world import SCENARIOS, World, build_world, sector_stub, signal_stub  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "docs" / "android" / "contract" / "examples"
TOKEN = "test-token-123"


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def worlds(tmp_path_factory) -> dict:
    base = tmp_path_factory.mktemp("bff_worlds")
    return {s: build_world(base, s, token=TOKEN) for s in SCENARIOS}


def make_client(world: World, **kw) -> TestClient:
    app = create_app(world.settings, now_fn=lambda: world.now, signal_fn=signal_stub, sector_for=sector_stub)
    return TestClient(app, base_url="http://testserver", raise_server_exceptions=False, **kw)


@pytest.fixture
def client_for(worlds):
    def make(scenario: str) -> TestClient:
        return make_client(worlds[scenario])
    return make


AUTH = {"X-Paper-Token": TOKEN}
