"""Health check and system status router."""
from __future__ import annotations

from fastapi import APIRouter

from live_runner.git_lock import read_authorized_info
from live_runner.idempotency import IdempotencyGuard
from data.db.connection import get_session

router = APIRouter()


@router.get("/health", tags=["System"])
def health_check():
    """System health and deployment lock status."""
    with get_session() as session:
        guard = IdempotencyGuard(session)
        last_run = guard.get_last_run()

    auth_info = read_authorized_info()
    from config import load_config
    from engine_core.mode import current_mode
    try:
        cfg = load_config()
        mode = current_mode(cfg)
    except Exception:
        mode = "UNKNOWN"

    return {
        "status": "ok",
        "mode": mode,
        "authorized": auth_info.get("authorized", False),
        "sha_locked": auth_info.get("sha_matches", False),
        "tree_clean": auth_info.get("tree_clean", False),
        "authorized_sha": auth_info.get("authorized_sha", "")[:8] if auth_info.get("authorized_sha") else None,
        "last_pipeline_run": last_run,
    }
