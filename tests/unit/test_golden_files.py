"""The frozen golden files under tests/golden are exactly what was committed (sha256), internally consistent, and complete."""
import hashlib
import json
from pathlib import Path

import pandas as pd

GOLD = Path(__file__).resolve().parents[1] / "golden"


def test_every_golden_file_matches_its_recorded_sha256_and_nothing_is_unlisted():
    sums = dict(reversed(line.split("  ", 1)) for line in (GOLD / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if line.strip())
    on_disk = {p.name for p in GOLD.iterdir() if p.name != "SHA256SUMS"}
    assert set(sums) == on_disk and len(on_disk) == 5
    for name, digest in sums.items():
        assert hashlib.sha256((GOLD / name).read_bytes()).hexdigest() == digest, name


def test_the_frozen_scan_summary_matches_the_frozen_residual_list():
    s = json.loads((GOLD / "engine_scan_summary.json").read_text(encoding="utf-8"))
    assert (s["large_before"], s["large_after"], s["removed"], s["created"]) == (764, 267, 499, 2)
    r = pd.read_csv(GOLD / "engine_scan.csv")
    assert len(r) == s["large_after"] and {k: int(v) for k, v in r.groupby("category").size().items()} == s["remaining_by_category"]
    assert int(r["was_big_before_adjustment"].sum()) + s["created"] == s["large_after"]            # remaining = still big before adjusting + created by adjusting


def test_the_frozen_samples_and_verification_rows_are_complete():
    j = json.loads((GOLD / "asof_120_samples.json").read_text(encoding="utf-8"))
    assert len(j["samples"]) == 120 and j["rng_seed"] == 7 and all(len(x["raw_sha256"]) == 64 and len(x["adj_sha256"]) == 64 for x in j["samples"])
    v = pd.read_csv(GOLD / "verification_old_path.csv")
    assert len(v) == 57 and (v["result"] == "PASS").all()
