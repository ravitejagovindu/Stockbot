"""The trial ledger (restructure Phase 7): where trials are recorded so the number of attempts is auditable and corrections can use it.

Records live next to this module in ``records/`` (see docs/restructure/LEDGER_MANIFEST.md): the hash-chained trial ledger of the rejected CFG-01..06 search, the
exploratory ledger (a sha256 pin, never a chain) and the pre-registration yaml. NOTHING in a ledger row depends on a file path, so records can be moved.

This module holds the ledger WRITERS, extracted from ``scripts/provenance/select_candidate.py`` (which stays as provenance and now calls them):
  * ``register`` writes a REGISTRATION row (yaml hash, gate hash, config budget); re-registration needs a reason;
  * ``record_exploratory`` logs dry runs / diagnostic runs (they still count; no chain);
  * the FAMILY helper records N strategies of one family TOGETHER: one registration row fixes the family size, and one results row must cover every member,
    so a multiplicity correction applies across the whole family and no member can be dropped from the count. Family rows use the same chain primitives
    as the trial ledger (``stockbot.validation.prereg_lock``).
No strategy knowledge here: a family member is anything with ``id``, ``version`` and ``config_hash()`` (a ``StrategySpec``).
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from stockbot.validation import prereg_lock as pl

RECORDS = Path(__file__).resolve().parent / "records"
TRIAL_LEDGER = RECORDS / "trial_ledger.csv"
EXPLORATORY_LEDGER = RECORDS / "trial_ledger_exploratory.csv"
PREREG_YAML = RECORDS / "pre_registered_configs.yaml"
FAMILY_LEDGER = RECORDS / "family_ledger.csv"                 # created by the first register_family call

PreRegistrationError = pl.PreRegistrationError
FAMILY_COLUMNS = ["timestamp_utc", "commit_sha", "family_id", "row_type", "members_json", "budget", "gates_sha256", "reason", "results_json", "prev_hash", "row_hash"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class LedgerStatus:
    rows: int
    last_hash: str


def verify(path: Path = TRIAL_LEDGER) -> LedgerStatus:
    """Raise PreRegistrationError if any row was altered, deleted or reordered; otherwise the row count and the last row hash."""
    pl.verify_ledger(path)
    _, recs = pl.read_ledger(path)
    return LedgerStatus(len(recs), recs[-1]["row_hash"] if recs else pl.GENESIS)


# ---------------------------------------------------------------- the trial ledger (extracted from select_candidate.py)
def register(*, ledger: Path, yaml_path: Path, gate_params: dict, candidate_ids: Sequence[str], git_sha: str, reason: Optional[str] = None, now: Optional[str] = None) -> dict:
    """Write the REGISTRATION row (YAML hash, gate hash, config budget = number of candidates). A second registration needs ``reason`` (it is recorded)."""
    if Path(ledger).exists():
        pl.upgrade_ledger(ledger)
        pl.verify_ledger(ledger)
        if pl.latest_registration(ledger) and not reason:
            raise PreRegistrationError("a REGISTRATION row already exists; re-registering needs --reregister-reason (it is recorded).")
    else:
        Path(ledger).parent.mkdir(parents=True, exist_ok=True)
        header = ["timestamp_utc", "commit_sha", "selected_config", "selection_reason"] + [f"{cid}_gate_reached" for cid in candidate_ids] + pl.EXTRA_COLUMNS
        with open(ledger, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)
    rec = {"timestamp_utc": now or _now(), "commit_sha": git_sha, "selected_config": "N/A", "selection_reason": reason or "initial registration", "row_type": "REGISTRATION",
           "yaml_sha256": pl.sha256_text_file(yaml_path), "gates_sha256": pl.gates_hash(gate_params), "budget": len(candidate_ids)}
    pl.append_row(ledger, rec)
    return rec


def record_exploratory(*, path: Path, note: str, selected: Optional[str], gate_reached: Mapping, git_sha: str, source: str, now: Optional[str] = None) -> None:
    """Dry-run / diagnostic runs are still counted (F6). No hash chain by design (decision e): the file is pinned by its sha256 instead.
    ``source`` is a free-text label of what was run (the legacy writer put an outputs directory here)."""
    new = not Path(path).exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp_utc", "commit_sha", "outputs_dir", "mode", "selected_config", "gate_reached_json"])
        w.writerow([now or _now(), git_sha, source, note, selected or "NONE", json.dumps(dict(gate_reached), sort_keys=True)])


# ---------------------------------------------------------------- family-level helper
def _members(members: Sequence[Any]) -> list:
    if not members:
        raise PreRegistrationError("a family needs at least one member")
    out = [{"id": m.id, "version": m.version, "config_hash": m.config_hash()} for m in members]
    ids = [m["id"] for m in out]
    if len(set(ids)) != len(ids):
        raise PreRegistrationError(f"duplicate strategy ids in one family: {sorted(i for i in ids if ids.count(i) > 1)}")
    return sorted(out, key=lambda m: m["id"])


def _family_rows(path: Path, family_id: str) -> list:
    if not Path(path).exists():
        return []
    pl.verify_ledger(path)
    return [r for r in pl.read_ledger(path)[1] if r["family_id"] == family_id]


def _append_family(path: Path, rec: dict) -> None:
    if not Path(path).exists():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(FAMILY_COLUMNS)
    pl.append_row(path, {**{c: "" for c in FAMILY_COLUMNS}, **rec})


def register_family(*, path: Path, family_id: str, members: Sequence[Any], gate_params: dict, git_sha: str, reason: Optional[str] = None, now: Optional[str] = None) -> dict:
    """Record the whole family at once (budget = number of members). Registering the same family again needs ``reason`` (recorded), so the count cannot be reset silently."""
    mem = _members(members)
    if any(r["row_type"] == "FAMILY_REGISTRATION" for r in _family_rows(path, family_id)) and not reason:
        raise PreRegistrationError(f"family {family_id} is already registered; registering it again needs a reason (it is recorded).")
    rec = {"timestamp_utc": now or _now(), "commit_sha": git_sha, "family_id": family_id, "row_type": "FAMILY_REGISTRATION",
           "members_json": json.dumps(mem, sort_keys=True), "budget": len(mem), "gates_sha256": pl.gates_hash(gate_params), "reason": reason or "initial registration"}
    _append_family(path, rec)
    return rec


def _latest_registration(path: Path, family_id: str) -> dict:
    regs = [r for r in _family_rows(path, family_id) if r["row_type"] == "FAMILY_REGISTRATION"]
    if not regs:
        raise PreRegistrationError(f"family {family_id} is not registered")
    return regs[-1]


def family_members(path: Path, family_id: str) -> list:
    return json.loads(_latest_registration(path, family_id)["members_json"])


def family_budget(path: Path, family_id: str) -> int:
    """The number of trials the multiplicity correction must account for: the registered family size."""
    return int(_latest_registration(path, family_id)["budget"])


def record_family_results(*, path: Path, family_id: str, results: Mapping[str, Mapping], git_sha: str, reason: Optional[str] = None, now: Optional[str] = None) -> dict:
    """Record the results of every member together. All registered members must be present and nothing else: a member cannot be left out of the count.
    A second results row for the same registration needs ``reason``."""
    reg = _latest_registration(path, family_id)
    expected = {m["id"] for m in json.loads(reg["members_json"])}
    got = set(results)
    if got != expected:
        raise PreRegistrationError(f"results must cover exactly the registered members: missing {sorted(expected - got)}, unexpected {sorted(got - expected)}")
    rows = _family_rows(path, family_id)
    last_reg_hash = reg["row_hash"]
    after = rows[rows.index(reg) + 1:]
    if any(r["row_type"] == "FAMILY_RESULTS" for r in after) and not reason:
        raise PreRegistrationError(f"results for family {family_id} are already recorded; a second set needs a reason (it is recorded).")
    rec = {"timestamp_utc": now or _now(), "commit_sha": git_sha, "family_id": family_id, "row_type": "FAMILY_RESULTS", "members_json": reg["members_json"],
           "budget": int(reg["budget"]), "gates_sha256": reg["gates_sha256"], "reason": reason or f"registration {last_reg_hash[:12]}",
           "results_json": json.dumps({k: dict(v) for k, v in sorted(results.items())}, sort_keys=True, default=str)}
    _append_family(path, rec)
    return rec
