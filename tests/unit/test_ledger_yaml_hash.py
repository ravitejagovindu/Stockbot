"""The pre-registration yaml must stay byte-identical: its sha256 is recorded in the trial ledger (restructure reviewer decision 2)."""
import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")          # a Windows checkout with autocrlf must not change the verdict


def test_pre_registered_configs_yaml_matches_the_ledger_hash():
    rows = list(csv.DictReader(open(ROOT / "backtest" / "outputs" / "trial_ledger.csv", encoding="utf-8", newline="")))
    recorded = {r["yaml_sha256"] for r in rows if r.get("yaml_sha256")}
    assert recorded, "no yaml_sha256 in the ledger"
    actual = hashlib.sha256(_norm((ROOT / "backtest" / "pre_registered_configs.yaml").read_bytes())).hexdigest()
    assert actual in recorded, (actual, recorded)
