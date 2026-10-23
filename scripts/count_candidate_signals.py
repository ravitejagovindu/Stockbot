"""
scripts/count_candidate_signals.py — Count candidate signals per config across 2020-2026.
Pure signal count (no forward P&L, no outcome leakage).
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import date
from collections import defaultdict
import pandas as pd
from sqlalchemy import select

from config import load_config
from data.db.connection import get_session
from data.db.models import MarketDataLake
from engine_core.candidate_builder import build_candidate_dicts
from engine_core.entry_filters import passes_trend_filter, passes_breakout, rs_return
from engine_core.universe_screener import UniverseScreener
from engine_core.regime_filter import RegimeFilter
from engine_core.regime_gates import is_bull, bull_correction_active, nifty_sma

def count_signals():
    cfg = load_config()
    with get_session() as s:
        screener = UniverseScreener(cfg, s)
        regime = RegimeFilter(cfg, s)
        sma_n = int(cfg.get("macro", {}).get("bull_entry_sma_period", 0))

        days_raw = (
            s.execute(
                select(MarketDataLake.trade_date)
                .distinct()
                .where(MarketDataLake.trade_date >= date(2020, 1, 1), MarketDataLake.trade_date <= date(2026, 10, 16))
                .order_by(MarketDataLake.trade_date)
            )
            .scalars()
            .all()
        )
        days = [d.date() if hasattr(d, "date") else date.fromisoformat(str(d)) for d in days_raw]

        print(f"Counting candidate tickets across {len(days)} trading sessions...")

        # We want to count tickets generated for:
        # CFG-00: All breakout candidates
        # Top 40% RS
        # Top 30% RS
        # Top 20% RS
        counts = defaultdict(lambda: {"W1": 0, "W2": 0, "Pooled": 0})

        for d in days:
            rs = regime.evaluate(d)
            ks = bool(rs.kill_switch_active)
            nsma = nifty_sma(s, cfg, d, sma_n) if sma_n else None
            if ks or (sma_n and bull_correction_active(rs.nifty_close, rs.nifty_sma200, nsma)):
                continue

            window = "W1" if d < date(2022, 1, 1) else "W2"

            all_syms = screener._get_all_symbols(d)
            passed = []
            for sym in all_syms:
                if sym in ("NIFTY50_INDEX", "INDIA_VIX"):
                    continue
                if not screener.screen_single(sym, d, apply_event_gates=False).passed:
                    continue
                passed.append(sym)

            if not passed:
                continue

            cands_raw = build_candidate_dicts(s, cfg, passed, d)
            ef = cfg.get("entry_filters", {})
            fast_sma = int(ef.get("trend_fast_sma", 50))
            slow_sma = int(ef.get("trend_slow_sma", 200))
            lookback = int(ef.get("breakout_lookback", 20))
            rs_lookback = int(ef.get("rs_lookback_days", 63))

            breakout_cands = []
            for c in cands_raw:
                adj = c["adjusted_ohlcv"]
                close, high = adj["close_adj"], adj["high_adj"]
                if not passes_trend_filter(close, fast_sma, slow_sma):
                    continue
                if not passes_breakout(close, high, lookback):
                    continue
                d_c = dict(c)
                d_c["rs_3m"] = rs_return(close, rs_lookback)
                breakout_cands.append(d_c)

            n_breakout = len(breakout_cands)
            if n_breakout == 0:
                continue

            # Sort descending by RS
            breakout_cands.sort(key=lambda c: (-c["rs_3m"] if pd.notna(c["rs_3m"]) else 1e9, c["symbol"]))

            # Count candidates under each rule
            # CFG-00: All
            counts["CFG-00 (All Breakouts)"][window] += n_breakout
            counts["CFG-00 (All Breakouts)"]["Pooled"] += n_breakout

            # Top 40%
            k_40 = max(1, int(round(n_breakout * 0.40)))
            counts["Top 40% RS"][window] += k_40
            counts["Top 40% RS"]["Pooled"] += k_40

            # Top 30%
            k_30 = max(1, int(round(n_breakout * 0.30)))
            counts["Top 30% RS"][window] += k_30
            counts["Top 30% RS"]["Pooled"] += k_30

            # Top 20%
            k_20 = max(1, int(round(n_breakout * 0.20)))
            counts["Top 20% RS"][window] += k_20
            counts["Top 20% RS"]["Pooled"] += k_20

        print("\nCandidate Signal Counts (Tickets Generated Before Portfolio Caps):")
        for k, v in counts.items():
            print(f"{k:25s}: W1={v['W1']:4d} | W2={v['W2']:4d} | Pooled={v['Pooled']:4d}")

if __name__ == "__main__":
    count_signals()
