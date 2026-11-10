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
    "strategies": {"data"},                      # plus the single engine module in STRATEGY_ENGINE_ALLOWED
    "backtest": {"config", "data", "universe", "risk", "engine", "strategies"},
    "live": {"config", "data", "universe", "risk", "engine", "strategies", "validation"},          # never backtest; validation: trade-R reporting used by the (legacy) analytics routers
    "validation": {"config", "data", "risk", "backtest", "engine", "universe"},     # never live; risk: R definitions (Q2); engine + universe: the baseline reuses the engine stepping and the shared eligibility (Q5)
    "data_checks": {"config", "data"},
}
# the one engine module a strategy folder may import (exit-policy interface types for a strategy-owned policy); prefix match on dotted names, so
# stockbot.engine.exit_policies (the shared library) and every other engine module stay forbidden
STRATEGY_ENGINE_ALLOWED = ("stockbot.engine.exit_policy",)
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
    return p[2] if len(p) > 2 and p[1] == "strategies" and p[2] not in ("base", "registry", "spec") else None


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
                permitted = pkg == "strategies" and tgt == "engine" and any(name == a or name.startswith(a + ".") for a in STRATEGY_ENGINE_ALLOWED)
                if not permitted:
                    out.add((mod, name, f"{pkg} may not import {tgt}"))
            # strategies: never another strategy; engine and the rest see only the interface (strategies.base) and the registry
            sn = _strategy_name(mod)
            if sn and tgt == "strategies" and len(q) > 2 and q[2] not in ("base", "registry", "spec") and q[2] != sn:
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
    # live: routers moved unmodified and flagged for rework; pipeline/lock/state still legacy
}
# non-stockbot legacy .py files still under the top-level data/ folder -> phase that removes/moves them
LEGACY_DATA_PY = {}
