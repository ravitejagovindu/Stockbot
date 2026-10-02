"""
FInsight Trading Engine — CLI Entry Point for Backtesting
"""
import argparse
import sys
from pathlib import Path
from datetime import date
from config import load_config
from data.db.connection import get_session
import pandas as pd

from backtest.pass1_naive_run import Pass1NaiveRun
from backtest.bifurcated_scraper.earnings_scraper import EarningsScraper
from backtest.bifurcated_scraper.asm_gsm_pdf_scraper import ASMGSMPDFScraper
from backtest.pass2_compliant_run import Pass2CompliantRun
from backtest.audit_generator import AuditGenerator

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pass1", action="store_true")
    parser.add_argument("--scrape", action="store_true")
    parser.add_argument("--pass2", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    config = load_config()
    out_dir = Path(__file__).parent / "outputs"
    out_dir.mkdir(exist_ok=True)

    if args.all:
        args.pass1 = True
        args.scrape = True
        args.pass2 = True
        args.audit = True
        print("\n[WARNING] Running --all skips manual verification of ASM/GSM PDFs.\n")

    if args.pass1:
        print("\n--- Running Pass 1 (Naive Run) ---")
        with get_session() as session:
            p1 = Pass1NaiveRun(config)
            for regime in config["backtest"]["regimes"]:
                df = p1.run(
                    regime["name"],
                    date.fromisoformat(regime["start"]),
                    date.fromisoformat(regime["end"]),
                    config["backtest"]["initial_equity"],
                    session
                )
                p1.output_csv(df, regime["name"])

    if args.scrape:
        print("\n--- Running Bifurcated Scrapers ---")
        e_scraper = EarningsScraper()
        a_scraper = ASMGSMPDFScraper()
        for regime in config["backtest"]["regimes"]:
            p = str(out_dir / f"candidate_trades_{regime['name']}.csv")
            if Path(p).exists():
                e_scraper.scrape_candidates(p)
                
                # ASM/GSM Stub
                df = pd.read_csv(p)
                symbols = df["symbol"].unique().tolist()
                asm_df = a_scraper.build_surveillance_timeline(symbols, date.fromisoformat(regime["start"]), date.fromisoformat(regime["end"]))
                asm_df.to_csv(out_dir / f"pending_asm_gsm_matches_{regime['name']}.csv", index=False)

    if args.pass2:
        print("\n--- Running Pass 2 (Compliant Run) ---")
        results = {}
        with get_session() as session:
            p2 = Pass2CompliantRun(config)
            for regime in config["backtest"]["regimes"]:
                r_name = regime["name"]
                res = p2.run(
                    r_name,
                    str(out_dir / f"candidate_trades_{r_name}.csv"),
                    str(out_dir / f"pending_asm_gsm_matches_{r_name}.csv"),  # Assume manually verified
                    str(out_dir / f"historical_earnings_{r_name}.csv"),
                    config["backtest"]["initial_equity"],
                    session
                )
                results[r_name] = res
                
                # Pass data over for audit
                AuditGenerator().generate(results, config)

    if args.audit and not args.pass2:
        print("\n--- Generating Audit Ledger ---")
        print("Run --pass2 to trigger audit generation.")

if __name__ == "__main__":
    main()
