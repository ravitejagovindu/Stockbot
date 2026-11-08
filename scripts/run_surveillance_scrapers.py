"""scripts/run_surveillance_scrapers.py — the earnings / ASM-GSM scrapers that used to run inside ``backtest/run_backtest.py --scrape`` (F10).

They use the network, so they are NOT part of a backtest any more (a backtest raises on any network call, see ``backtest/no_network.py``).
Run this explicitly BEFORE a Pass 2 backtest; it writes ``historical_earnings_<regime>.csv`` / ``pending_asm_gsm_matches_<regime>.csv`` in backtest/outputs.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest.bifurcated_scraper.asm_gsm_pdf_scraper import ASMGSMPDFScraper      # noqa: E402
from backtest.bifurcated_scraper.earnings_scraper import EarningsScraper          # noqa: E402
from config import load_config                                                    # noqa: E402


def main() -> None:
    config = load_config()
    out_dir = ROOT / "backtest" / "outputs"
    regimes = [r for r in config.get("backtest", {}).get("regimes", []) if r.get("role", "TUNE") == "TUNE"]
    e_scraper, a_scraper = EarningsScraper(), ASMGSMPDFScraper()
    for regime in regimes:
        name = regime["name"]
        p = out_dir / f"candidate_trades_{name}.csv"
        if not p.exists():
            continue
        e_scraper.scrape_candidates(str(p))
        symbols = pd.read_csv(p)["symbol"].unique().tolist()
        asm_df = a_scraper.build_surveillance_timeline(symbols, date.fromisoformat(regime["start"]), date.fromisoformat(regime["end"]))
        asm_df.to_csv(out_dir / f"pending_asm_gsm_matches_{name}.csv", index=False)


if __name__ == "__main__":
    main()
