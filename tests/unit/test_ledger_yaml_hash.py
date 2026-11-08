"""The pre-registration yaml must stay byte-identical: its sha256 is recorded in the trial ledger (restructure reviewer decision 2)."""
import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")          # a Windows checkout with autocrlf must not change the verdict


def test_pre_registered_configs_yaml_matches_the_ledger_hash():
    rows = list(csv.DictReader(open(ROOT / "stockbot" / "validation" / "ledger" / "records" / "trial_ledger.csv", encoding="utf-8", newline="")))
    recorded = {r["yaml_sha256"] for r in rows if r.get("yaml_sha256")}
    assert recorded, "no yaml_sha256 in the ledger"
    actual = hashlib.sha256(_norm((ROOT / "stockbot" / "validation" / "ledger" / "records" / "pre_registered_configs.yaml").read_bytes())).hexdigest()
    assert actual in recorded, (actual, recorded)


REC = ROOT / "stockbot" / "validation" / "ledger" / "records"


def test_the_trial_ledger_chain_verifies_at_its_validation_location_and_names_no_path():
    from stockbot.validation import prereg_lock as pl
    pl.verify_ledger(REC / "trial_ledger.csv")                                      # raises if a row was altered, deleted or reordered
    header, recs = pl.read_ledger(REC / "trial_ledger.csv")
    assert len(recs) == 2 and recs[-1]["row_hash"] == "869d1bd13d592ce635bed70c10081d6b2037a79272f64dabe21819a9152125d1"     # last hash recorded before the move
    assert not any(any(m in str(v) for m in ("\\", ".csv", ".yaml", ".py", "outputs", "backtest/")) for r in recs for v in r.values())                # the chain depends on no file path


def test_the_exploratory_ledger_is_unchanged_and_has_no_chain():
    raw = (REC / "trial_ledger_exploratory.csv").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "090c1c178bc434a1fa0778a97aa94b5f0abe320f03513090cab0891f8dbe2049"
    assert b"row_hash" not in raw and b"prev_hash" not in raw                         # decision (e): a sha256 pin, never a chain


def test_what_remains_of_the_old_outputs_is_what_the_ledger_and_the_decisions_need():
    """Phase 10 deleted the stale outputs; the files the ledger or a reviewer decision refers to must still be there (docs/restructure/LEDGER_MANIFEST.md)."""
    import csv as _csv
    kept = ROOT / "backtest" / "outputs_recomputed_net"
    assert len(list(kept.iterdir())) == 27 and (kept / "recompute_comparison.csv").exists() and (kept / "selection_decision.json").exists()
    import subprocess
    tracked = subprocess.run(["git", "ls-files", "backtest"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert [t for t in tracked if t.startswith("backtest/outputs/")] == ["backtest/outputs/selection_decision.json"] and not [t for t in tracked if "outputs_v1_stale" in t]
    rows = list(_csv.DictReader(open(REC / "trial_ledger_exploratory.csv", encoding="utf-8", newline="")))
    named = {Path(r["outputs_dir"].replace("\\", "/")).name for r in rows}
    assert "outputs_recomputed_net" in named and all((ROOT / "backtest" / n).exists() for n in named if n.startswith("outputs"))      # every outputs folder the exploratory ledger names still exists
    assert not [t for t in tracked if t.endswith(".py")]                                                                              # no code left in backtest/
