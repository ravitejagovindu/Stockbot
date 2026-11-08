"""docs/restructure/tools/move_modules.py — Phase 2 pure-move helper.

Usage: py docs/restructure/tools/move_modules.py <group>      (run from the repo root, working tree clean)
For each module in the group: `git mv` the file to its new place, then rewrite every reference in tracked .py files (outside ui/):
  - dotted module names   engine_core.adjustments -> stockbot.data.adjustments   (imports, patch-target strings, docstrings)
  - slash paths           engine_core/adjustments.py -> stockbot/data/adjustments.py
  - `from <old package> import <moved module>` -> `from <new package> import <moved module>`
Nothing else is touched (file-path arithmetic such as Path(__file__).parents[n] is fixed by hand in the same commit).
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ING = ["asm_gsm_refresher", "base_ingestor", "bhavcopy_ingestor", "ca_evidence", "corporate_actions_ingestor", "earnings_calendar_ingestor",
       "index_vix_ingestor", "local_csv_ingestor", "nse_corporate_actions_history", "ohlcv_ingestor", "securities_ingestor", "shares_outstanding_ingestor"]
GROUPS = {
    "data_core": [("engine_core.adjustments", "stockbot.data.adjustments"), ("engine_core.indicators", "stockbot.data.indicators")],
    "risk": [("engine_core.costs", "stockbot.risk.costs"), ("engine_core.sector_map", "stockbot.risk.sector_map")],
    "config": [("engine_core.mode", "stockbot.config.mode"), ("logging_config", "stockbot.config.logging_config")],
    "validation": [("engine_core.max_t_bootstrap", "stockbot.validation.max_t_bootstrap"), ("engine_core.prereg_lock", "stockbot.validation.prereg_lock"),
                   ("engine_core.trade_metrics", "stockbot.validation.trade_metrics")],
    "engine": [("engine_core.corporate_action_events", "stockbot.engine.corporate_action_events")],
    "data_checks": [("engine_core.preflight", "stockbot.data_checks.preflight"), ("data.quality_checker", "stockbot.data_checks.quality_checker")],
    "ingestion": [(f"data.ingestion.{m}", f"stockbot.data.ingestion.{m}") for m in ING],
    "universe_backtest": [("backtest.exclusions", "stockbot.universe.exclusions"), ("backtest.no_network", "stockbot.backtest.no_network")],
    "live": [("live_runner.idempotency", "stockbot.live.idempotency"), ("live_runner.main", "stockbot.live.main"), ("live_runner.scheduler", "stockbot.live.scheduler")]
            + [(f"live_runner.routers.{r}", f"stockbot.live.api.{r}") for r in ("analytics", "health", "ledger", "portfolio", "positions", "regime", "watchlist")],
}
SPECIAL_INIT = {"ingestion": [("data/ingestion/__init__.py", "stockbot/data/ingestion/__init__.py")],
                "live": [("live_runner/routers/__init__.py", "stockbot/live/api/__init__.py")]}


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def main(group):
    pairs = GROUPS[group]
    for old, new in pairs:
        src, dst = Path(old.replace(".", "/") + ".py"), Path(new.replace(".", "/") + ".py")
        dst.parent.mkdir(parents=True, exist_ok=True)
        git("mv", str(src), str(dst))
    for src, dst in SPECIAL_INIT.get(group, []):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        if (ROOT / dst).exists():
            git("rm", "-f", str(dst))                       # the skeleton __init__ is replaced by the moved one (git history follows the move)
        git("mv", src, dst)
    files = [f for f in git("ls-files", "*.py").split("\n") if f and not f.startswith("ui/") and not f.startswith("docs/restructure/tools/")]
    # package-level form first: "from engine_core import prereg_lock" -> "from stockbot.validation import prereg_lock"
    pkg_forms = []
    for old, new in pairs:
        op, _, on = old.rpartition(".")
        np_, _, nn = new.rpartition(".")
        if op and on == nn:
            pkg_forms.append((re.compile(rf"from {re.escape(op)} import {on}\b"), f"from {np_} import {nn}"))
    dotted = sorted(pairs, key=lambda p: -len(p[0]))
    n_changed = 0
    for f in files:
        p = ROOT / f
        s0 = p.read_bytes().decode("utf-8")
        s = s0
        for rx, rep in pkg_forms:
            s = rx.sub(rep, s)
        for old, new in dotted:
            s = re.sub(rf"(?<![\w.]){re.escape(old)}(?![\w])", new, s)
            so, sn = old.replace(".", "/") + ".py", new.replace(".", "/") + ".py"
            s = re.sub(rf"(?<![\w/]){re.escape(so)}", sn, s)
        if s != s0:
            p.write_bytes(s.encode("utf-8"))
            n_changed += 1
    print(f"group {group}: moved {len(pairs)} modules, rewrote references in {n_changed} files")


if __name__ == "__main__":
    main(sys.argv[1])
