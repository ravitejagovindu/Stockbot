"""
scripts/count_candidate_signals.py — Fast candidate signal counter across 2020-2026.
Counts signals/tickets generated per config per window (NO forward P&L, zero outcome leakage).
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from sqlalchemy import select

from config import load_config
from data.db.connection import get_session
from data.db.models import MarketDataLake
from engine_core.candidate_builder import build_candidate_dicts
from engine_core.entry_filters import passes_breakout, passes_trend_filter, rs_return
from engine_core.indicators import sma
from engine_core.regime_filter import RegimeFilter
from engine_core.regime_gates import bull_correction_active, is_bull, nifty_sma
from engine_core.universe_screener import UniverseScreener


def count_all_signals():
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
        day_set = set(days)

        print(f"Counting candidate tickets across {len(days)} trading sessions...")

        ef = cfg.get("entry_filters", {})
        fast_sma = int(ef.get("trend_fast_sma", 50))
        slow_sma = int(ef.get("trend_slow_sma", 200))
        lookback = int(ef.get("breakout_lookback", 20))
        rs_lookback = int(ef.get("rs_lookback_days", 63))

        # We will track:
        # CFG-00: All breakout candidates
        # CFG-01: RS Top 40% (Gap 3.0%)
        # CFG-02: RS Top 40% (Gap 1.5%)
        # CFG-03: RS Top 40% (Gap 1.5% + Breadth >= 50%)
        # CFG-04: RS Top 30% (Gap 3.0%)
        # CFG-05: RS Top 30% (Gap 1.5%)
        # CFG-06: RS Top 30% (Gap 1.5% + Breadth >= 50%)
        # Also explore Top 50% and Top 20% for reviewer context
        counts = defaultdict(lambda: {"W1": 0, "W2": 0, "Pooled": 0})

        for day_idx, d in enumerate(days):
            rs = regime.evaluate(d)
            ks = bool(rs.kill_switch_active)
            nsma = nifty_sma(s, cfg, d, sma_n) if sma_n else None
            if ks or (sma_n and bull_correction_active(rs.nifty_close, rs.nifty_sma200, nsma)):
                continue

            window = "W1" if d < date(2022, 1, 1) else "W2"
            next_day = days[day_idx + 1] if day_idx + 1 < len(days) else None

            # Fast indexed fetch of symbols trading on date d with turnover >= 1cr
            all_syms = s.execute(
                select(MarketDataLake.symbol)
                .where(MarketDataLake.trade_date == d)
                .where((MarketDataLake.close_raw * MarketDataLake.volume_raw) >= 10000000)
                .where(MarketDataLake.symbol.notin_(["NIFTY50_INDEX", "INDIA_VIX"]))
            ).scalars().all()

            passed = []
            for sym in all_syms:
                if not screener.screen_single(sym, d, apply_event_gates=False).passed:
                    continue
                passed.append(sym)

            if not passed:
                continue

            cands_raw = build_candidate_dicts(s, cfg, passed, d)
            if not cands_raw:
                continue

            # Compute Market Breadth (% of screened stocks with close > 50 SMA)
            above_50 = 0
            for c in cands_raw:
                cl = c["adjusted_ohlcv"]["close_adj"]
                if len(cl) >= 50 and cl.iloc[-1] > cl.rolling(50).mean().iloc[-1]:
                    above_50 += 1
            breadth_pct = (above_50 / len(cands_raw)) * 100.0 if cands_raw else 0.0

            # Filter for trend and breakout
            breakouts = []
            for c in cands_raw:
                adj = c["adjusted_ohlcv"]
                close, high = adj["close_adj"], adj["high_adj"]
                if not passes_trend_filter(close, fast_sma, slow_sma):
                    continue
                if not passes_breakout(close, high, lookback):
                    continue
                d_c = dict(c)
                d_c["rs_3m"] = rs_return(close, rs_lookback)
                d_c["close_signal"] = float(close.iloc[-1])
                breakouts.append(d_c)

            n_b = len(breakouts)
            if n_b == 0:
                continue

            # Sort descending by RS then symbol ASC
            breakouts.sort(key=lambda c: (-c["rs_3m"] if pd.notna(c["rs_3m"]) else 1e9, c["symbol"]))

            # Next open prices for gap check if next day exists
            next_opens = {}
            if next_day:
                next_rows = s.execute(
                    select(MarketDataLake.symbol, MarketDataLake.open_raw)
                    .where(MarketDataLake.trade_date == next_day)
                    .where(MarketDataLake.symbol.in_([b["symbol"] for b in breakouts]))
                ).all()
                next_opens = {r[0]: float(r[1]) for r in next_rows}

            def check_gap(b, max_gap_pct):
                sym = b["symbol"]
                if sym not in next_opens:
                    return False
                op = next_opens[sym]
                cl = b["close_signal"]
                return (op / cl - 1.0) * 100.0 <= max_gap_pct

            # CFG-00: All breakouts with standard 3.0% gap
            cfg00_valid = [b for b in breakouts if check_gap(b, 3.0)]
            counts["CFG-00 (Baseline Breakout, Gap<=3%)"][window] += len(cfg00_valid)
            counts["CFG-00 (Baseline Breakout, Gap<=3%)"]["Pooled"] += len(cfg00_valid)

            # Top 50%
            k50 = max(1, int(round(n_b * 0.50)))
            top50 = breakouts[:k50]
            counts["RS Top 50% (Gap<=3.0%)"][window] += len([b for b in top50 if check_gap(b, 3.0)])
            counts["RS Top 50% (Gap<=3.0%)"]["Pooled"] += len([b for b in top50 if check_gap(b, 3.0)])

            # Top 40% (CFG-01, CFG-02, CFG-03)
            k40 = max(1, int(round(n_b * 0.40)))
            top40 = breakouts[:k40]
            counts["CFG-01 (RS Top 40%, Gap<=3.0%)"][window] += len([b for b in top40 if check_gap(b, 3.0)])
            counts["CFG-01 (RS Top 40%, Gap<=3.0%)"]["Pooled"] += len([b for b in top40 if check_gap(b, 3.0)])

            counts["CFG-02 (RS Top 40%, Gap<=1.5%)"][window] += len([b for b in top40 if check_gap(b, 1.5)])
            counts["CFG-02 (RS Top 40%, Gap<=1.5%)"]["Pooled"] += len([b for b in top40 if check_gap(b, 1.5)])

            if breadth_pct >= 50.0:
                counts["CFG-03 (RS Top 40%, Gap<=1.5%, Breadth>=50%)"][window] += len([b for b in top40 if check_gap(b, 1.5)])
                counts["CFG-03 (RS Top 40%, Gap<=1.5%, Breadth>=50%)"]["Pooled"] += len([b for b in top40 if check_gap(b, 1.5)])

            # Top 30% (CFG-04, CFG-05, CFG-06)
            k30 = max(1, int(round(n_b * 0.30)))
            top30 = breakouts[:k30]
            counts["CFG-04 (RS Top 30%, Gap<=3.0%)"][window] += len([b for b in top30 if check_gap(b, 3.0)])
            counts["CFG-04 (RS Top 30%, Gap<=3.0%)"]["Pooled"] += len([b for b in top30 if check_gap(b, 3.0)])

            counts["CFG-05 (RS Top 30%, Gap<=1.5%)"][window] += len([b for b in top30 if check_gap(b, 1.5)])
            counts["CFG-05 (RS Top 30%, Gap<=1.5%)"]["Pooled"] += len([b for b in top30 if check_gap(b, 1.5)])

            if breadth_pct >= 50.0:
                counts["CFG-06 (RS Top 30%, Gap<=1.5%, Breadth>=50%)"][window] += len([b for b in top30 if check_gap(b, 1.5)])
                counts["CFG-06 (RS Top 30%, Gap<=1.5%, Breadth>=50%)"]["Pooled"] += len([b for b in top30 if check_gap(b, 1.5)])

            # Top 20% for reference
            k20 = max(1, int(round(n_b * 0.20)))
            top20 = breakouts[:k20]
            counts["Reference (RS Top 20%, Gap<=1.5%, Breadth>=50%)"][window] += (
                len([b for b in top20 if check_gap(b, 1.5)]) if breadth_pct >= 50.0 else 0
            )
            counts["Reference (RS Top 20%, Gap<=1.5%, Breadth>=50%)"]["Pooled"] += (
                len([b for b in top20 if check_gap(b, 1.5)]) if breadth_pct >= 50.0 else 0
            )

        print("\n=========================================================================================")
        print("  CANDIDATE SIGNAL COUNTS PER CONFIG PER WINDOW (Tickets Generated Before Sizing/Slots)")
        print("=========================================================================================")
        rows = []
        for k, v in counts.items():
            rows.append({
                "Configuration": k,
                "W1 (2020-21)": v["W1"],
                "W2 (2022-26)": v["W2"],
                "Pooled": v["Pooled"],
                "Meets W1 >=20 Floor": "YES" if v["W1"] >= 20 else "NO (FAIL)",
                "Meets Pooled >=80 Floor": "YES" if v["Pooled"] >= 80 else "NO (FAIL)",
            })
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    count_all_signals()
