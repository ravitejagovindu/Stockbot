"""Shared research runner (engine only, no baselines) for the market-switch comparison: ONE backtest of ONE strategy with or without the shared default overlays.

  py scripts/run_with_market_switch.py --strategy near_52w_high --out DIR --execute [--overlays default|none] [--start 2016-01-01] [--end 2026-10-16] [--lake PATH]

--overlays default (the default) applies the shared default overlays (market_switch_v1); --overlays none passes default_overlays=[] (the explicit opt-out: the manifest says "overlays": []).
Without --execute only the plan is printed. The strategy's own spec, exit policy and the shared config are used unchanged; STOCKBOT_VIEW is honoured (the run manifest records asof_view).
Descriptive comparison runs only; nothing here registers anything or writes a ledger row.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.backtest.manifest import shared_config_hash  # noqa: E402
from stockbot.backtest.outputs import write_run_files  # noqa: E402
from stockbot.backtest.runner import run_backtest  # noqa: E402
from stockbot.config.paths import lake_path  # noqa: E402
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import active_view_name  # noqa: E402
from stockbot.data.sector_map import SectorLookup  # noqa: E402
from stockbot.engine.decide import EventData  # noqa: E402
from stockbot.overlays import describe_default_overlays  # noqa: E402
from stockbot.strategies.registry import StrategyRegistry  # noqa: E402

STRATEGIES = {"near_52w_high": ("stockbot.strategies.near_52w_high", "NearHighStrategy"),
              "pullback_uptrend": ("stockbot.strategies.pullback_uptrend", "PullbackUptrendStrategy"),
              "short_term_reversal": ("stockbot.strategies.short_term_reversal", "ShortTermReversalStrategy")}


def build_strategy(sid: str):
    import importlib
    mod, cls = STRATEGIES[sid]
    m = importlib.import_module(mod)
    registry = StrategyRegistry()
    m.register(registry)
    return getattr(m, cls)(registry.get(sid))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", required=True, choices=sorted(STRATEGIES))
    ap.add_argument("--lake")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--out")
    ap.add_argument("--overlays", choices=("default", "none"), default="default")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_shared_config()
    strategy = build_strategy(args.strategy)
    ids = [] if args.overlays == "none" else None
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    plan = {"strategy": args.strategy, "spec_config_hash": strategy.spec.config_hash(), "exit_policy": strategy.spec.exit_policy, "window": [start.isoformat(), end.isoformat()],
            "overlays": describe_default_overlays(cfg, ids), "shared_config_hash": shared_config_hash(cfg, ids), "asof_view": active_view_name(), "lake": str(args.lake or lake_path())}
    print(json.dumps(plan, indent=1))
    if not args.execute:
        print("plan only: pass --execute to run", file=sys.stderr)
        return 0
    if not args.out:
        print("--out is required with --execute", file=sys.stderr)
        return 2
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        print(f"refusing to write into a non-empty directory: {out}", file=sys.stderr)
        return 2
    res = run_backtest(args.lake or lake_path(), start, end, cfg.backtest.initial_equity, [strategy], None, cfg, EventData(sectors=SectorLookup(), asm_ranges={}), default_overlays=ids)
    write_run_files(res, out)
    print(f"sessions {len(res.decisions)}; closed trades {len(res.trades)}; written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
