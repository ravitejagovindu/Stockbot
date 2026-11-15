"""Research wiring for the riskadj_momentum strategy: ONE run of stockbot.backtest.runner.run_backtest with the shared config, the strategy-owned exit policy trailing_atr3_floor8 (passed as
``policies_for(specs, extra=[TrailingAtr3Floor8()])``: the library does not know it) and the shared sector lookup (SectorLookup over data/reference/sector_map.csv; every unmapped symbol is its own
sector, UNMAPPED:<symbol>).

It does NOT run unless --execute is given: without it the script only prints the plan (window, spec hash, shared-config hash, asof_view). One strategy, one spec, one window, no sweep.
The wiring is proven on a fixture lake in tests/unit/test_riskadj_momentum_scripts.py; the registered run waits for the owner's family registration (docs/strategies/riskadj_momentum/RUN_COMMANDS.md).

  py scripts/research_riskadj_momentum.py [--lake PATH] [--start 2016-01-01] [--end 2026-10-16] [--out DIR] [--execute]

END-OF-WINDOW RULE (registered before any result; docs/strategies/riskadj_momentum/PREREGISTRATION.md): a position still open after the last session is closed at the last session's close with the
normal exit slippage and costs (the shared runner already does this, reason END_OF_WINDOW) and COUNTS as a usable trade in the gates, T1 and T2. The shared gate code treats the exit reason
END_OF_WINDOW as "not usable", and it must not be edited; so in trades.json (the file the gates read) such a trade carries exit_reason "END_OF_WINDOW_COUNTED", with the engine's own reason kept in
``exit_reason_engine`` ("END_OF_WINDOW") and ``end_of_window`` true. Everything else about the trade is the engine's record, unchanged. The number of such trades is printed and written to
manifest.json under ``end_of_window``.

Outputs under --out: manifest.json (the run manifest, with asof_view and the end_of_window block), trades.json, equity_curve.json, daily.json (equity and cash at every close) and blocked.json.
Nothing is printed about P&L. Known limitation: no ASM/GSM ranges for the historical window.
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
from stockbot.data.asof import active_view_name  # noqa: E402
from stockbot.data.sector_map import SectorLookup  # noqa: E402
from stockbot.engine.decide import EventData  # noqa: E402
from stockbot.engine.exit_policies.registry import policies_for  # noqa: E402
from stockbot.strategies.registry import StrategyRegistry  # noqa: E402
from stockbot.strategies.riskadj_momentum import RiskAdjMomentumStrategy, TrailingAtr3Floor8, register  # noqa: E402

DEFAULT_START, DEFAULT_END = "2016-01-01", "2026-10-16"
ENGINE_EOW, COUNTED_EOW = "END_OF_WINDOW", "END_OF_WINDOW_COUNTED"


def trade_records(trades) -> list:
    """The engine's closed trades as dicts; an END_OF_WINDOW closure is relabelled so that the shared gate code counts it (see the module docstring)."""
    out = []
    for t in trades:
        d = dataclasses.asdict(t)
        d["end_of_window"] = d["exit_reason"] == ENGINE_EOW
        d["exit_reason_engine"] = d["exit_reason"]
        if d["end_of_window"]:
            d["exit_reason"] = COUNTED_EOW
        out.append(d)
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Research wiring for riskadj_momentum (prints the plan; runs one backtest only with --execute).")
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
    strategy = RiskAdjMomentumStrategy(registry.get("riskadj_momentum"))
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    plan = {"strategy": strategy.spec.id, "version": strategy.spec.version, "status": strategy.spec.status, "spec_config_hash": strategy.spec.config_hash(),
            "exit_policy": strategy.spec.exit_policy, "params": dict(strategy.spec.params), "window": [start.isoformat(), end.isoformat()],
            "initial_equity": cfg.backtest.initial_equity, "shared_config_hash": shared_config_hash(cfg), "asof_view": active_view_name(), "lake": str(args.lake or lake_path()),
            "end_of_window_rule": "open positions are closed at the last close with normal costs and slippage and COUNT as usable trades"}
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
    policies = policies_for([strategy.spec], extra=[TrailingAtr3Floor8()])
    res = run_backtest(args.lake or lake_path(), start, end, cfg.backtest.initial_equity, [strategy], policies, cfg, EventData(sectors=SectorLookup(), asm_ranges={}))
    trades = trade_records(res.trades)
    n_eow = sum(1 for t in trades if t["end_of_window"])
    manifest = dict(res.manifest)
    manifest["end_of_window"] = {"rule": "closed at the last session close, normal costs and slippage, counted as usable trades", "trades": n_eow, "closed_trades_total": len(trades),
                                 "closed_before_window_end": len(trades) - n_eow, "label_in_trades_json": COUNTED_EOW, "engine_reason": ENGINE_EOW}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    (out / "trades.json").write_text(json.dumps(trades, indent=1, default=str), encoding="utf-8")
    (out / "equity_curve.json").write_text(json.dumps({d.isoformat(): v for d, v in res.equity_curve.items()}, indent=1), encoding="utf-8")
    (out / "daily.json").write_text(json.dumps({dec.as_of.isoformat(): {"equity": res.equity_curve[dec.as_of], "cash": dec.cash_after} for dec in res.decisions}, indent=1), encoding="utf-8")
    (out / "blocked.json").write_text(json.dumps([{"date": dec.as_of.isoformat(), "strategy_id": b.strategy_id, "symbol": b.symbol, "reason": b.reason, "stage": b.stage}
                                                  for dec in res.decisions for b in dec.blocked], indent=1), encoding="utf-8")
    print(f"sessions {len(res.decisions)}; closed trades {len(trades)} (of which closed at the window end: {n_eow}); written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
