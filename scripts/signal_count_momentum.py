"""Thin command-line wrapper: logic in stockbot.data_checks.momentum_signal_count (momentum groundwork task); this wrapper only injects the shared eligibility rule, because data_checks may not import stockbot.universe. Read-only on the lake; counts only, no returns. Run: py scripts/signal_count_momentum.py --help"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data_checks.momentum_signal_count import cli  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402


def main(argv=None) -> int:
    cfg = load_shared_config()
    pr = cfg.portfolio_risk
    return cli(lambda view: eligible_symbols(view, cfg.universe), max_positions=pr.max_concurrent_positions, risk_pct=pr.max_loss_pct_per_trade,
               sector_cap_pct=pr.max_sector_exposure_pct, argv=argv)


if __name__ == "__main__":
    sys.exit(main())
