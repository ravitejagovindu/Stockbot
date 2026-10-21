"""FInsight Trading Engine — CLI Entry Point for Backtesting.

Usage:
    python -m backtest.run_backtest --pass1
    python -m backtest.run_backtest --pass2 [--allow-unverified]
    python -m backtest.run_backtest --freeze
    python -m backtest.run_backtest --test --pass1 --pass2
    python -m backtest.run_backtest --audit
    python -m backtest.run_backtest --all
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
from sqlalchemy import distinct, select

from backtest.audit_generator import generate, summarize
from backtest.bifurcated_scraper.asm_gsm_pdf_scraper import ASMGSMPDFScraper
from backtest.bifurcated_scraper.earnings_scraper import EarningsScraper
from backtest.exclusions import Exclusions
from backtest.simulator import SimResult, Simulator
from config import load_config
from data.db.connection import get_session
from data.db.models import MarketDataLake

_ROOT = Path(__file__).resolve().parents[1]


def _git_hash_config() -> str:
    try:
        return subprocess.check_output(
            ["git", "hash-object", "strategy_config.yaml"],
            text=True,
            cwd=_ROOT,
        ).strip()
    except Exception:
        return "unknown"


def _fetch_nifty_series(session, config: dict, start_date: date, end_date: date) -> pd.Series:
    sym = config.get("data", {}).get("nifty_symbol", "NIFTY50_INDEX")
    rows = session.execute(
        select(MarketDataLake.trade_date, MarketDataLake.close_raw)
        .where(MarketDataLake.symbol == sym)
        .where(MarketDataLake.trade_date >= start_date, MarketDataLake.trade_date <= end_date)
        .order_by(MarketDataLake.trade_date)
    ).all()
    if not rows:
        return pd.Series(dtype="float64")
    return pd.Series(
        data=[float(r.close_raw) for r in rows],
        index=[r.trade_date for r in rows],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="StockBot Backtest Runner")
    parser.add_argument("--pass1", action="store_true", help="Run Pass 1 (naive, exclusions=None)")
    parser.add_argument("--scrape", action="store_true", help="Run bifurcated scrapers")
    parser.add_argument("--pass2", action="store_true", help="Run Pass 2 (compliant, fail-closed exclusions)")
    parser.add_argument("--audit", action="store_true", help="Generate audit.json from Pass 2 results")
    parser.add_argument("--allow-unverified", action="store_true", help="Allow unverified ASM/GSM or earnings in Pass 2")
    parser.add_argument("--freeze", action="store_true", help="Freeze strategy_config.yaml SHA to outputs/FROZEN.sha")
    parser.add_argument("--test", action="store_true", help="Run only TEST windows (requires config matching FROZEN.sha)")
    parser.add_argument("--all", action="store_true", help="Run Pass 1, Pass 2, and Audit")
    args = parser.parse_args()

    config = load_config()
    out_dir = Path(__file__).parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.all:
        args.pass1 = True
        args.pass2 = True
        args.audit = True

    regimes = config.get("backtest", {}).get("regimes", [])
    if args.test:
        frozen_path = out_dir / "FROZEN.sha"
        if not frozen_path.exists():
            print("ERROR: --test requires a frozen config, but outputs/FROZEN.sha does not exist. Run with --freeze first.")
            sys.exit(1)
        frozen_sha = frozen_path.read_text(encoding="utf-8").strip()
        current_sha = _git_hash_config()
        if current_sha != frozen_sha:
            print(f"REFUSED: current strategy_config.yaml hash ({current_sha[:8]}) does not match FROZEN.sha ({frozen_sha[:8]}).")
            sys.exit(1)
        target_regimes = [r for r in regimes if r.get("role") == "TEST"]
        if not target_regimes:
            print("No regimes with role='TEST' found in strategy_config.yaml.")
            sys.exit(1)
    else:
        # Default: TUNE regimes (or all if role not specified)
        target_regimes = [r for r in regimes if r.get("role", "TUNE") == "TUNE"]

    initial_equity = float(config.get("backtest", {}).get("initial_equity", 1_000_000.0))
    pass2_sim_results: Dict[str, SimResult] = {}

    if args.scrape:
        print("\n--- Running Bifurcated Scrapers ---")
        e_scraper = EarningsScraper()
        a_scraper = ASMGSMPDFScraper()
        for regime in target_regimes:
            r_name = regime["name"]
            p = out_dir / f"candidate_trades_{r_name}.csv"
            if p.exists():
                e_scraper.scrape_candidates(str(p))
                df = pd.read_csv(p)
                symbols = df["symbol"].unique().tolist()
                asm_df = a_scraper.build_surveillance_timeline(
                    symbols,
                    date.fromisoformat(regime["start"]),
                    date.fromisoformat(regime["end"]),
                )
                asm_df.to_csv(out_dir / f"pending_asm_gsm_matches_{r_name}.csv", index=False)

    with get_session() as session:
        for regime in target_regimes:
            name = regime["name"]
            s = date.fromisoformat(regime["start"])
            e = date.fromisoformat(regime["end"])
            sim = Simulator(config, session)

            if args.pass1:
                print(f"\n--- Running Pass 1 (Naive) for {name} ({s} to {e}) ---")
                r1 = sim.run(s, e, initial_equity, exclusions=None)
                r1.trades.to_csv(out_dir / f"trades_pass1_{name}.csv", index=False)
                r1.equity.to_csv(out_dir / f"equity_pass1_{name}.csv")
                print(f"Pass 1 {name} complete: {len(r1.trades)} trades.")

            if args.pass2:
                print(f"\n--- Running Pass 2 (Compliant) for {name} ({s} to {e}) ---")
                block_days = int(config.get("trade_management", {}).get("binary_event_block_days", 14))
                known_ahead_days = int(config.get("earnings", {}).get("known_ahead_days", 7))
                exc = Exclusions.load(
                    out_dir,
                    name,
                    block_days=block_days,
                    known_ahead_days=known_ahead_days,
                    allow_unverified=args.allow_unverified,
                )
                r2 = sim.run(s, e, initial_equity, exclusions=exc)
                r2.trades.to_csv(out_dir / f"trades_pass2_{name}.csv", index=False)
                r2.equity.to_csv(out_dir / f"equity_pass2_{name}.csv")
                pd.DataFrame(r2.skipped, columns=["date", "symbol", "reason"]).to_csv(
                    out_dir / f"skipped_pass2_{name}.csv", index=False
                )
                pass2_sim_results[name] = r2
                print(f"Pass 2 {name} complete: {len(r2.trades)} trades.")

        if args.freeze:
            sha = _git_hash_config()
            (out_dir / "FROZEN.sha").write_text(sha, encoding="utf-8")
            print(f"\n[FREEZE] Strategy config hash saved to outputs/FROZEN.sha: {sha}")

        if args.audit:
            print("\n--- Generating Audit Ledger ---")
            summaries = {}
            for regime in target_regimes:
                name = regime["name"]
                s = date.fromisoformat(regime["start"])
                e = date.fromisoformat(regime["end"])
                res = pass2_sim_results.get(name)
                if res is None:
                    # Try loading from disk
                    t_path = out_dir / f"trades_pass2_{name}.csv"
                    eq_path = out_dir / f"equity_pass2_{name}.csv"
                    if t_path.exists() and eq_path.exists():
                        trades_df = pd.read_csv(t_path)
                        eq_df = pd.read_csv(eq_path, index_col=0)
                        eq_series = eq_df.iloc[:, 0]
                        res = SimResult(trades_df, eq_series, compliance_applied=True)
                    else:
                        print(f"WARNING: No Pass 2 results found for {name}. Run with --pass2 first.")
                        continue

                nifty = _fetch_nifty_series(session, config, s, e)
                summaries[name] = summarize(res, nifty, config, initial_equity)

            if summaries:
                audit = generate(summaries, config, out_dir)
                print(f"Audit generated. Overall pass: {audit['dual_gate']['overall_pass']}")
            else:
                print("No summaries produced for audit.")


if __name__ == "__main__":
    main()
