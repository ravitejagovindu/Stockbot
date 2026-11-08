"""Import-boundary rules for stockbot/ (restructure plan section 2) and the checker used by tests/unit/test_import_boundaries.py.

`check(root)` walks <root>/stockbot/**/*.py with the AST (imports anywhere in a file, including inside functions) and returns violations as
(importer, imported, rule) tuples.  The same function is run on the real tree and on the seeded-violation fixtures in tests/fixtures/boundary_violations/.

Legacy (not yet moved/replaced) modules still live at their old top-level paths.  An import from stockbot/ to such a module, or any other
edge the rules forbid, is allowed ONLY as an explicit, temporary entry of LEGACY_ALLOWLIST, with the phase that removes it.  Stale entries
(an edge that no longer exists) fail the test, so the list can only shrink; at STOP 5 it must be empty (STOCKBOT_FINAL_CHECK=1 runs that test).
"""
from __future__ import annotations

import ast
from pathlib import Path

PACKAGES = ("config", "data", "universe", "risk", "engine", "strategies", "backtest", "live", "validation", "data_checks")
LEGACY_TOP = ("data", "engine_core", "live_runner", "backtest", "config", "logging_config", "scripts", "tests")
# which stockbot packages each stockbot package may import (itself is always allowed)
ALLOWED = {
    "config": set(),
    "data": {"config"},
    "universe": {"config", "data"},
    "risk": {"config", "data"},
    "engine": {"config", "data", "universe", "risk", "strategies"},
    "strategies": {"data"},
    "backtest": {"config", "data", "universe", "risk", "engine", "strategies"},
    "live": {"config", "data", "universe", "risk", "engine", "strategies"},          # never backtest
    "validation": {"config", "data", "backtest"},                                  # never live
    "data_checks": {"config", "data"},
}
NETWORK_LIBS = {"requests", "urllib", "urllib3", "yfinance", "httpx", "aiohttp", "http", "socket", "ftplib", "smtplib"}
DB_LIBS = {"sqlalchemy", "sqlite3"}
NO_NETWORK_PKGS = {"backtest", "engine", "strategies", "risk"}
NO_DB_PKGS = {"engine", "strategies"}                 # may not receive or open a session/connection
NETWORK_EXEMPT = {"stockbot.backtest.no_network"}      # the guard itself patches socket


def _imports(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                yield a.name, n.lineno
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            yield n.module, n.lineno
            for a in n.names:
                yield f"{n.module}.{a.name}", n.lineno
        elif isinstance(n, ast.ImportFrom) and n.level:
            yield "." * n.level + (n.module or ""), n.lineno


def _modname(root: Path, f: Path) -> str:
    rel = f.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def edges(root: Path):
    """Yield (importer_module, imported_dotted_name, lineno, file) for every import in <root>/stockbot."""
    for f in sorted((root / "stockbot").rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        mod = _modname(root, f)
        for name, ln in _imports(tree):
            yield mod, name, ln, f


def _strategy_name(mod: str):
    p = mod.split(".")
    return p[2] if len(p) > 2 and p[1] == "strategies" and p[2] not in ("base", "registry") else None


def check(root: Path):
    """Return the set of (importer, imported, rule) violations in <root>/stockbot (before the allowlist is applied)."""
    out = set()
    for mod, name, ln, f in edges(root):
        p = mod.split(".")
        pkg = p[1] if len(p) > 1 else None
        top = name.split(".")[0]
        if "sys.path" in name:
            continue
        if top == "stockbot":
            q = name.split(".")
            tgt = q[1] if len(q) > 1 else None
            if pkg in ALLOWED and tgt in PACKAGES and tgt != pkg and tgt not in ALLOWED[pkg]:
                out.add((mod, name, f"{pkg} may not import {tgt}"))
            # strategies: never another strategy; engine and the rest see only the interface (strategies.base) and the registry
            sn = _strategy_name(mod)
            if sn and tgt == "strategies" and len(q) > 2 and q[2] not in ("base", "registry") and q[2] != sn:
                out.add((mod, name, "a strategy may not import another strategy"))
            if pkg in ("engine", "risk", "universe", "data", "data_checks", "validation") and tgt == "strategies" and len(q) > 2 and q[2] not in ("base", "registry"):
                out.add((mod, name, f"{pkg} may only import strategies.base / registry"))
        elif top in LEGACY_TOP and top != "tests":
            out.add((mod, name, "import of a legacy (old top-level) module"))
        elif top in NETWORK_LIBS and pkg in NO_NETWORK_PKGS and mod not in NETWORK_EXEMPT:
            out.add((mod, name, f"network library inside {pkg}"))
        elif top in DB_LIBS and pkg in NO_DB_PKGS:
            out.add((mod, name, f"database library inside {pkg} (no session/connection)"))
    # sys.path edits inside stockbot/
    for f in sorted((root / "stockbot").rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        if "sys.path.append" in src or "sys.path.insert" in src:
            out.add((_modname(root, f), "sys.path", "sys.path edit inside stockbot/"))
    # the legacy data/db layer is also off limits for engine/strategies/risk/universe even through the new names
    return out


# (importer, imported-name-prefix) -> phase that removes the edge.  Importer is a module name; imported is the exact dotted name found.
LEGACY_ALLOWLIST = {
    # ingestion and quality checks still use the old session helper / ORM: replaced by the read-only lake connection and the state-store split
    **{(f"stockbot.data.ingestion.{m}", n): "Phase 3 (db layer split)" for m, ns in {
        "asm_gsm_refresher": ["data.db.connection"], "bhavcopy_ingestor": ["data.db.connection"],
        "corporate_actions_ingestor": ["data.db.connection", "data.db.models"], "earnings_calendar_ingestor": ["data.db.connection", "data.db.models"],
        "index_vix_ingestor": ["data.db.connection", "data.db.models"], "local_csv_ingestor": ["data.db.connection"],
        "ohlcv_ingestor": ["data.db.connection", "data.db.models"], "securities_ingestor": ["data.db.connection"],
        "shares_outstanding_ingestor": ["data.db.connection", "data.db.models"]}.items() for n in ns},
    ("stockbot.data_checks.quality_checker", "data.db.connection"): "Phase 3 (db layer split)",
    ("stockbot.engine.corporate_action_events", "engine_core.lifecycle_rules"): "Phase 6 (engine; rescale_for_action and PosState move)",
    # live: routers moved unmodified and flagged for rework; pipeline/lock/state still legacy
    ("stockbot.live.api.analytics", "data.db.connection"): "Phase 9 (live package)",
    ("stockbot.live.api.analytics", "engine_core.analytics_loop"): "Phase 9 (live package)",
    ("stockbot.live.api.health", "config"): "Phase 4 (config split)",
    ("stockbot.live.api.health", "data.db.connection"): "Phase 9 (live package)",
    ("stockbot.live.api.health", "live_runner.git_lock"): "Phase 4 (git lock dropped)",
    ("stockbot.live.api.ledger", "data.db.connection"): "Phase 9 (live package)",
    ("stockbot.live.api.ledger", "data.db.models"): "Phase 9 (live package)",
    ("stockbot.live.api.ledger", "engine_core.account_ledger"): "Phase 9 (live package)",
    ("stockbot.live.api.portfolio", "config"): "Phase 4 (config split)",
    ("stockbot.live.api.portfolio", "data.db.connection"): "Phase 9 (live package)",
    ("stockbot.live.api.portfolio", "data.db.models"): "Phase 9 (live package)",
    ("stockbot.live.api.portfolio", "engine_core.equity"): "Phase 9 (live package)",
    ("stockbot.live.api.positions", "config"): "Phase 4 (config split)",
    ("stockbot.live.api.positions", "data.db.connection"): "Phase 9 (live package)",
    ("stockbot.live.api.positions", "data.db.models"): "Phase 9 (live package)",
    ("stockbot.live.api.positions", "engine_core.analytics_loop"): "Phase 9 (live package)",
    ("stockbot.live.api.positions", "engine_core.position_service"): "Phase 9 (live package)",
    ("stockbot.live.api.regime", "config"): "Phase 4 (config split)",
    ("stockbot.live.api.regime", "data.db.connection"): "Phase 9 (live package)",
    ("stockbot.live.api.watchlist", "data.db.connection"): "Phase 9 (live package)",
    ("stockbot.live.idempotency", "data.db.models"): "Phase 9 (live package; state store)",
    ("stockbot.live.main", "data.db.connection"): "Phase 9 (live package)",
    ("stockbot.live.main", "live_runner.git_lock"): "Phase 4 (git lock dropped)",
    ("stockbot.live.scheduler", "config"): "Phase 4 (config split)",
    ("stockbot.live.scheduler", "data.db.connection"): "Phase 9 (live package)",
    ("stockbot.live.scheduler", "data.db.models"): "Phase 9 (live package)",
    ("stockbot.live.scheduler", "live_runner.git_lock"): "Phase 4 (git lock dropped)",
    ("stockbot.live.scheduler", "live_runner.pipeline"): "Phase 6/9 (EOD runner replaced)",
}
# non-stockbot legacy .py files still under the top-level data/ folder -> phase that removes/moves them
LEGACY_DATA_PY = {
    "data/__init__.py": "Phase 3 (db layer split)",
    "data/db/__init__.py": "Phase 3 (db layer split)",
    "data/db/connection.py": "Phase 3 (db layer split)",
    "data/db/models.py": "Phase 3 (db layer split) / Phase 9 (state store)",
    "data/db/migration_f3_corporate_actions.py": "Phase 8 (provenance disposition)",
    "data/db/migration_phase2.py": "Phase 8 (provenance disposition)",
    "data/db/migration_phase3_paper.py": "Phase 8 (provenance disposition)",
    "data/db/migration_securities_master.py": "Phase 8 (provenance disposition)",
    "data/ingestion/pit_shares.py": "Phase 8 (provenance disposition; F2b NOT USED)",
}
