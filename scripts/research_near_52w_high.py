"""Research wiring for the near_52w_high strategy: ONE run of stockbot.backtest.runner.run_backtest with the shared config, the exit policy the strategy's spec names (fixed_hold_40, built by
run_backtest from the spec because policies=None), and the sector lookup live uses (SectorLookup over data/reference/sector_map.csv; unmapped symbols share UNKNOWN).

It does NOT run unless --execute is given: without it the script only prints the plan (window, spec hash, shared-config hash). There is no parameter sweep and no loop over variants:
one strategy, one spec, one window. The registered run is STOP 4 of the task; STOP 2 only proves the wiring on a fixture lake in tests/unit/test_research_near_52w_high.py.

  py scripts/research_near_52w_high.py [--lake PATH] [--start 2016-01-01] [--end 2026-10-16] [--out DIR] [--execute]

Outputs under --out: manifest.json (the run manifest), trades.json (closed trades, END_OF_WINDOW closures included), equity_curve.json. Nothing is printed about P&L.
Known limitation: no ASM/GSM surveillance ranges are supplied for the historical window (the snapshots exist only for recent dates), so that shared exclusion is not applied.
"""
import argparse
import dataclasses
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.backtest.manifest import shared_config_hash  # noqa: E402
from stockbot.backtest.runner import run_backtest  # noqa: E402
from stockbot.config.paths import lake_path  # noqa: E402
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.engine.decide import EventData  # noqa: E402
from stockbot.live.runner import SectorLookup  # noqa: E402
from stockbot.strategies.near_52w_high import NearHighStrategy, register  # noqa: E402
from stockbot.strategies.registry import StrategyRegistry  # noqa: E402

DEFAULT_START, DEFAULT_END = "2016-01-01", "2026-10-16"       # window A, fixed by the owner at the STOP 1 review


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Research wiring for near_52w_high (prints the plan; runs one backtest only with --execute).")
    ap.add_argument("--lake", help="path of finsight.db (default: STOCKBOT_DB or <repo>/finsight.db); opened read-only")
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--out", help="output directory (must not exist or be empty); required with --execute")
    ap.add_argument("--execute", action="store_true", help="run the backtest (without it only the plan is printed)")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_shared_config()
    registry = StrategyRegistry()
    register(registry)
    strategy = NearHighStrategy(registry.get("near_52w_high"))
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    plan = {"strategy": strategy.spec.id, "version": strategy.spec.version, "status": strategy.spec.status, "spec_config_hash": strategy.spec.config_hash(),
            "exit_policy": strategy.spec.exit_policy, "params": dict(strategy.spec.params), "window": [start.isoformat(), end.isoformat()],
            "initial_equity": cfg.backtest.initial_equity, "shared_config_hash": shared_config_hash(cfg), "lake": str(args.lake or lake_path())}
    print(json.dumps(plan, indent=1))
    if not args.execute:
        print("plan only: pass --execute to run the backtest", file=sys.stderr)
        return 0
    if not args.out:
        print("--out is required with --execute", file=sys.stderr)
        return 2
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        print(f"refusing to write into a non-empty directory: {out}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    res = run_backtest(args.lake or lake_path(), start, end, cfg.backtest.initial_equity, [strategy], None, cfg, EventData(sectors=SectorLookup(), asm_ranges={}))
    (out / "manifest.json").write_text(json.dumps(res.manifest, indent=1, default=str), encoding="utf-8")
    (out / "trades.json").write_text(json.dumps([dataclasses.asdict(t) for t in res.trades], indent=1, default=str), encoding="utf-8")
    (out / "equity_curve.json").write_text(json.dumps({d.isoformat(): v for d, v in res.equity_curve.items()}, indent=1), encoding="utf-8")
    print(f"sessions {len(res.decisions)}; closed trades {len(res.trades)}; written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
