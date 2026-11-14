"""Thin command-line wrapper: logic in scripts/strategies/short_term_reversal/signal_count.py (short_term_reversal Stage 1); this wrapper only injects the shared eligibility rule and the shared caps. Read-only on the lake; counts only, no returns. Run: py scripts/signal_count_short_term_reversal.py --help"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "strategies" / "short_term_reversal"))

from signal_count import cli  # noqa: E402
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402


def main(argv=None) -> int:
    cfg = load_shared_config()
    pr = cfg.portfolio_risk
    return cli(lambda view: eligible_symbols(view, cfg.universe), max_positions=pr.max_concurrent_positions, risk_pct=pr.max_loss_pct_per_trade,
               max_total_risk_pct=pr.max_total_portfolio_risk_pct, sector_cap_pct=pr.max_sector_exposure_pct, argv=argv)


if __name__ == "__main__":
    sys.exit(main())
