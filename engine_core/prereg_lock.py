"""engine_core/prereg_lock.py — hash lock for the pre-registration and a tamper-evident trial ledger (F6).

* The SHA-256 of ``pre_registered_configs.yaml`` (line endings normalised) and of the selection-gate parameters are
  recorded in a REGISTRATION row of the trial ledger together with the registered config budget.
* Every ledger row carries ``prev_hash`` and ``row_hash`` (hash chain). Editing, deleting or re-ordering any earlier row
  breaks the chain and ``verify_ledger`` reports it. (A determined person with write access can rewrite the whole file;
  git history and the commit SHA stored in each row are the second line of defence.)
* ``select_candidate.py`` refuses to run when the YAML/gate hashes differ from the latest registration, when the number
  of CANDIDATE configs differs from the registered budget, or when the chain is broken.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Iterable

GENESIS = "GENESIS"
EXTRA_COLUMNS = ["row_type", "yaml_sha256", "gates_sha256", "budget", "prev_hash", "row_hash"]


class PreRegistrationError(RuntimeError):
    """Raised when the pre-registration lock, the config budget or the ledger chain does not verify."""


def sha256_text_file(path: Path) -> str:
    """SHA-256 of a text file with CRLF/CR normalised to LF (so Windows checkouts hash the same)."""
    data = Path(path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def gates_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _row_hash(prev_hash: str, fields: Iterable[str]) -> str:
    return hashlib.sha256((prev_hash + "\x1f" + "\x1f".join(str(f) for f in fields)).encode("utf-8")).hexdigest()


def read_ledger(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return [], []
    header, body = rows[0], rows[1:]
    recs = []
    for r in body:
        r = r + [""] * (len(header) - len(r))
        recs.append(dict(zip(header, r)))
    return header, recs


def _write_ledger(path: Path, header: list[str], recs: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in recs:
            w.writerow([r.get(h, "") for h in header])


def _content_fields(header: list[str], rec: dict) -> list[str]:
    return [rec.get(h, "") for h in header if h not in ("prev_hash", "row_hash")]


def upgrade_ledger(path: Path) -> bool:
    """Add the chain columns to a legacy ledger, keeping every legacy row and chaining them (idempotent)."""
    header, recs = read_ledger(path)
    if "row_hash" in header:
        return False
    header = header + EXTRA_COLUMNS
    prev = GENESIS
    for rec in recs:
        rec["row_type"] = rec.get("row_type") or "LEGACY"
        rec["prev_hash"] = prev
        rec["row_hash"] = _row_hash(prev, _content_fields(header, rec))
        prev = rec["row_hash"]
    _write_ledger(path, header, recs)
    return True


def verify_ledger(path: Path) -> None:
    header, recs = read_ledger(path)
    if "row_hash" not in header:
        raise PreRegistrationError(f"{path.name} has no hash chain; run `select_candidate.py --register`.")
    prev = GENESIS
    for i, rec in enumerate(recs, 1):
        if rec["prev_hash"] != prev:
            raise PreRegistrationError(f"ledger chain broken at data row {i}: prev_hash mismatch (row deleted or reordered?)")
        if rec["row_hash"] != _row_hash(prev, _content_fields(header, rec)):
            raise PreRegistrationError(f"ledger chain broken at data row {i}: content was altered")
        prev = rec["row_hash"]


def append_row(path: Path, rec: dict) -> None:
    """Append a chained row (the ledger must already be upgraded and verified)."""
    header, recs = read_ledger(path)
    prev = recs[-1]["row_hash"] if recs else GENESIS
    rec = dict(rec)
    rec["prev_hash"] = prev
    rec["row_hash"] = _row_hash(prev, _content_fields(header, rec))
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([rec.get(h, "") for h in header])


def latest_registration(path: Path) -> dict | None:
    _, recs = read_ledger(path)
    regs = [r for r in recs if r.get("row_type") == "REGISTRATION"]
    return regs[-1] if regs else None


def enforce(yaml_path: Path, ledger_path: Path, gate_params: dict, n_candidates: int) -> dict:
    """Raise PreRegistrationError unless ledger chain, YAML hash, gate hash and config budget all verify."""
    if not Path(ledger_path).exists():
        raise PreRegistrationError("no trial ledger found; register the pre-registration first.")
    verify_ledger(ledger_path)
    reg = latest_registration(ledger_path)
    if reg is None:
        raise PreRegistrationError("ledger has no REGISTRATION row; run `select_candidate.py --register` once.")
    if sha256_text_file(yaml_path) != reg["yaml_sha256"]:
        raise PreRegistrationError("pre_registered_configs.yaml differs from the registered hash (edited after registration).")
    if gates_hash(gate_params) != reg["gates_sha256"]:
        raise PreRegistrationError("selection gate parameters differ from the registered hash.")
    if int(reg["budget"]) != int(n_candidates):
        raise PreRegistrationError(
            f"{n_candidates} CANDIDATE configs found but the registered trial budget is {reg['budget']}.")
    return reg
