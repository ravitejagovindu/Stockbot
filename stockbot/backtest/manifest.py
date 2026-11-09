"""Run manifest (restructure plan Phase 6 Part B item 4): what a backtest run needs recorded so it can be reproduced and audited.

config hash (the shared config, canonical JSON) + each strategy's id, version and spec config hash (overlay ids/versions included) + git SHA + data snapshot id
(lake file name, size, mtime and last session; the 3.4 GB file is not hashed on every run) + seed + window + initial equity. Plain JSON-serialisable data.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


def shared_config_hash(shared_config) -> str:
    return hashlib.sha256(json.dumps(shared_config.flat(), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def git_sha(repo: Optional[Path] = None) -> Optional[str]:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo or Path(__file__).resolve().parents[2]), capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def data_snapshot_id(lake_path: Path, last_session: Optional[date]) -> dict:
    st = Path(lake_path).stat()
    return {"file": Path(lake_path).name, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "last_session": last_session.isoformat() if last_session else None}


def run_manifest(*, shared_config, strategies: Sequence, window: tuple, initial_equity: float, lake_path: Optional[Path] = None, last_session: Optional[date] = None,
                 seed: Optional[int] = None, sha: Optional[str] = None) -> dict[str, Any]:
    return {
        "shared_config_hash": shared_config_hash(shared_config),
        "strategies": {s.spec.id: {"version": s.spec.version, "config_hash": s.spec.config_hash(), "exit_policy": s.spec.exit_policy, "overlays": dict(s.spec.overlays)}
                       for s in sorted(strategies, key=lambda s: s.spec.id)},
        "git_sha": sha if sha is not None else git_sha(),
        "data_snapshot": data_snapshot_id(lake_path, last_session) if lake_path is not None else None,
        "seed": seed,
        "window": [window[0].isoformat(), window[1].isoformat()],
        "initial_equity": initial_equity,
    }
