"""Health check and system status router."""
from __future__ import annotations

from fastapi import APIRouter

from stockbot.live.idempotency import IdempotencyGuard
from data.db.connection import get_session

router = APIRouter()


@router.get("/health", tags=["System"])
def health_check():
    """System health and deployment lock status."""
    with get_session() as session:
        guard = IdempotencyGuard(session)
        last_run = guard.get_last_run()

    auth_info: dict = {}      # the Git-SHA deployment lock was dropped in restructure Phase 4; keys kept so the UI contract is unchanged{n}    from stockbot.config.legacy_loader import load_config
    from stockbot.config.mode import current_mode
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
