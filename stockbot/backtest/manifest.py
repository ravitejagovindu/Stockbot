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

from stockbot.data.asof import active_view_name
from stockbot.overlays import describe_effective_overlays


def shared_config_hash(shared_config, default_overlays: Optional[Sequence[str]] = None, strategies: Sequence = ()) -> str:
    """Hash of the shared config (canonical JSON). The ``overlays.*`` numbers are left out and the library overlays in force (shared defaults plus strategy-declared; id, version, numbers) are added
    only when there are any, so a run with no overlay hashes exactly as on master and a run with the market switch differs."""
    payload = {k: v for k, v in shared_config.flat().items() if not k.startswith("overlays.")}
    eff = describe_effective_overlays(shared_config, strategies, default_overlays)
    if eff:
        payload["overlays.effective"] = eff
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


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
                 seed: Optional[int] = None, sha: Optional[str] = None, default_overlays: Optional[Sequence[str]] = None, stale_exit_trades: Optional[Sequence] = None,
                 db_check: Optional[Mapping] = None) -> dict[str, Any]:
    """``db_check``: runcheck.manifest_block (db-guard); None leaves the block out, as in manifests written before the guard. ``stale_exit_trades``: the closed trades of the run with reason SYMBOL_NO_BARS (pass () when there are none); None leaves the stale_exit block out (callers that do not know the trades)."""
    out = {
        "shared_config_hash": shared_config_hash(shared_config, default_overlays, strategies),
        "overlays": describe_effective_overlays(shared_config, strategies, default_overlays),
        "strategies": {s.spec.id: {"version": s.spec.version, "config_hash": s.spec.config_hash(), "exit_policy": s.spec.exit_policy, "overlays": dict(s.spec.overlays)}
                       for s in sorted(strategies, key=lambda s: s.spec.id)},
        "git_sha": sha if sha is not None else git_sha(),
        "data_snapshot": data_snapshot_id(lake_path, last_session) if lake_path is not None else None,
        "seed": seed,
        "asof_view": active_view_name(),
        "window": [window[0].isoformat(), window[1].isoformat()],
        "initial_equity": initial_equity,
    }
    if db_check is not None:
        out["db_check"] = dict(db_check)          # db-guard R1/R4: file sha256 before/after (long step), correction counter, sealed dates and table digests before/after
    links = _symbol_links_block()
    if links is not None:
        out["symbol_links"] = links
    if stale_exit_trades is not None:
        out["stale_exit"] = stale_exit_block(shared_config, stale_exit_trades)
    return out


def _symbol_links_block() -> Optional[dict]:
    """Whether symbol links were in force for this run and which table (sha256 of data/reference/symbol_links.csv)."""
    from stockbot.config.paths import repo_root
    from stockbot.data import symbol_links
    p = repo_root() / "data" / "reference" / symbol_links.LINKS_FILE
    links = symbol_links.active()
    return {"enabled": symbol_links.enabled(), "linked_pairs": len(links.pairs) if links is not None else 0, "file_sha256": hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None}


def stale_exit_block(shared_config, trades: Sequence) -> dict:
    """Reporting only (never a gate): how many trades the no-bars rule closed (SYMBOL_NO_BARS), their list and their total net P&L."""
    rows = [t for t in trades if getattr(t, "exit_reason", None) == "SYMBOL_NO_BARS"]
    eng = getattr(shared_config, "engine", None)
    return {"sessions": getattr(eng, "stale_exit_sessions", None), "trades": len(rows), "net_pnl_total": float(sum(t.net_pnl for t in rows)),
            "list": [{"position_id": t.position_id, "symbol": t.symbol, "entry_date": t.entry_date.isoformat(), "exit_date": t.exit_date.isoformat(), "net_pnl": float(t.net_pnl)} for t in rows]}
