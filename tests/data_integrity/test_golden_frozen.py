"""Golden results FROZEN from the old engine path (tests/golden, written by docs/restructure/tools/freeze_golden.py before engine_core was deleted) and checked here against
the as-of view on the REAL lake (STOCKBOT_DATA_TESTS=1, read-only):

  1. the 120 (symbol, eval_date) samples: sha256 of the exact float64 bytes of the raw and adjusted frames equal what ``build_candidate_dicts`` returned;
  2. the post-adjustment engine scan (764 large moves -> 267, 499 removed, 2 created): the scan read through the view reproduces the frozen residual list and summary exactly.
The 57 verification rows through the view (and against their frozen engine factors) are in test_asof_view_real_db.py and test_corporate_actions_real_db.py."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

DB = Path(os.environ.get("STOCKBOT_DB") or Path(__file__).resolve().parents[2] / "finsight.db")
RUN = os.environ.get("STOCKBOT_DATA_TESTS") == "1"
pytestmark = pytest.mark.skipif(not RUN, reason="needs STOCKBOT_DATA_TESTS=1 and the real database")
GOLD = Path(__file__).resolve().parents[1] / "golden"


def frame_hash(df: pd.DataFrame) -> str:
    return hashlib.sha256(np.ascontiguousarray(df.to_numpy(dtype="float64")).tobytes() + "|".join(map(str, df.index)).encode()).hexdigest()


@pytest.fixture(scope="module")
def conn():
    from stockbot.data.lake import open_lake
    c = open_lake(DB)
    yield c
    c.close()


def test_the_frozen_120_samples_equal_the_view_bit_for_bit(conn):
    from stockbot.data.asof import AsOfView
    frozen = json.loads((GOLD / "asof_120_samples.json").read_text(encoding="utf-8"))["samples"]
    assert len(frozen) == 120
    mism = []
    for s in frozen:
        v = AsOfView(conn, date.fromisoformat(s["eval_date"]))
        raw, adj = v.raw_bars(s["symbol"], s["lookback"]), v.adjusted_bars(s["symbol"], s["lookback"])
        if not (len(raw) == s["lookback"] and frame_hash(raw) == s["raw_sha256"] and frame_hash(adj) == s["adj_sha256"]):
            mism.append((s["symbol"], s["eval_date"]))
    assert not mism, mism


def test_the_scan_through_the_view_reproduces_the_frozen_old_path_result(conn):
    from stockbot.data_checks.f2_engine_scan import compare_with_frozen, scan
    rdf, summary = scan(conn)
    assert (summary["large_before"], summary["large_after"], summary["removed"], summary["created"]) == (764, 267, 499, 2)
    assert compare_with_frozen(rdf, summary) == []
