"""Empirical testing of reviewer's selection hypotheses on 198 closed trades.

Optimized with indexed symbol queries. Evaluates:
1. Hypothesis 1: Volume Breakout Expansion (Volume >= 1.25x and 1.5x 20d avg volume)
2. Hypothesis 2: Tighter Entry Gap-up Limit (<= 1.5% and <= 1.0% Gap at Open)
3. Hypothesis 3: High Relative Strength (Top 3-Month RS Return >= 15%)
4. Hypothesis 4: Nifty 200 SMA Slope at Entry (Rising vs Flat/Falling)
5. Combined Selection Model
"""
from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
from sqlalchemy import desc, select, text

from data.db.connection import get_session
from data.db.models import MarketDataLake
from engine_core.sector_map import sector_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eval_hypotheses")


def load_trades():
    out_dir = _ROOT / "backtest" / "outputs"
    df1 = pd.read_csv(out_dir / "trades_pass1_window_2020_2021.csv")
    df1["window"] = "window_2020_2021"
    df2 = pd.read_csv(out_dir / "trades_pass1_window_2022_2026.csv")
    df2["window"] = "window_2022_2026"
    trades = pd.concat([df1, df2], ignore_index=True)
    trades["entry_date"] = pd.to_datetime(trades["entry_date"]).dt.date
    trades["one_r"] = trades["entry_price"] - trades["stop"]
    trades["realized_r"] = trades["pnl_net"] / (trades["one_r"] * trades["shares"])
    trades["sector"] = trades["symbol"].apply(sector_for)
    return trades


def run_evaluation():
    trades = load_trades()
    logger.info(f"Loaded {len(trades)} baseline trades.")

    enhanced = []
    with get_session() as session:
        # Pre-fetch Nifty 200 SMA slope
        nifty_rows = session.execute(
            select(MarketDataLake.trade_date, MarketDataLake.close_raw)
            .where(MarketDataLake.symbol == "NIFTY50_INDEX")
            .order_by(MarketDataLake.trade_date)
        ).all()
        n_df = pd.DataFrame(nifty_rows, columns=["trade_date", "close"])
        n_df["trade_date"] = pd.to_datetime(n_df["trade_date"]).dt.date
        n_df["sma200"] = n_df["close"].rolling(200).mean()
        n_df["sma50"] = n_df["close"].rolling(50).mean()
        n_df["sma200_slope"] = (n_df["sma200"] - n_df["sma200"].shift(20)) / n_df["sma200"].shift(20) * 100.0
        n_df["nifty_bull_trend"] = (n_df["close"] > n_df["sma200"]) & (n_df["sma50"] > n_df["sma200"]) & (n_df["sma200_slope"] > 0)
        n_map = n_df.set_index("trade_date").to_dict(orient="index")

        logger.info("Enriching trades with indexed volume ratios, gaps, and RS...")
        for _, row in trades.iterrows():
            sym = row["symbol"]
            ed = row["entry_date"]
            ep = row["entry_price"]

            # Query symbol bars using indexed lookup
            bars = session.execute(
                select(MarketDataLake.trade_date, MarketDataLake.close_raw, MarketDataLake.volume_raw)
                .where(MarketDataLake.symbol == sym)
                .where(MarketDataLake.trade_date <= ed)
                .order_by(desc(MarketDataLake.trade_date))
                .limit(65)
            ).all()

            vol_mult = 1.0
            gap_pct = 0.0
            rs_3m = 0.0

            if len(bars) >= 2:
                today_vol = float(bars[0][2])
                prior_vols = [float(b[2]) for b in bars[1:21]]
                avg_vol = np.mean(prior_vols) if prior_vols else today_vol
                vol_mult = today_vol / avg_vol if avg_vol > 0 else 1.0

                prior_close = float(bars[1][1])
                gap_pct = (ep - prior_close) / prior_close * 100.0 if prior_close > 0 else 0.0

            if len(bars) >= 60:
                p_now = float(bars[0][1])
                p_then = float(bars[-1][1])
                rs_3m = (p_now - p_then) / p_then * 100.0 if p_then > 0 else 0.0

            n_info = n_map.get(ed, {})
            n_slope = n_info.get("sma200_slope", 0.0)
            n_bull = n_info.get("nifty_bull_trend", False)

            d_row = dict(row)
            d_row["vol_mult"] = vol_mult
            d_row["gap_pct"] = gap_pct
            d_row["rs_3m"] = rs_3m
            d_row["n_slope"] = n_slope
            d_row["n_bull"] = n_bull
            enhanced.append(d_row)

    df = pd.DataFrame(enhanced)

    # -------------------------------------------------------------
    # STATISTICAL EVALUATION OF PRE-REGISTERED HYPOTHESES
    # -------------------------------------------------------------
    print("\n" + "=" * 85)
    print("        PRE-REGISTERED SELECTION HYPOTHESES EVALUATION (198 TRADES)")
    print("=" * 85)

    def print_metrics(name: str, subset: pd.DataFrame):
        w1 = subset[subset["window"] == "window_2020_2021"]
        w2 = subset[subset["window"] == "window_2022_2026"]

        def pf(s):
            w = s[s["pnl_net"] > 0]["pnl_net"].sum()
            l = abs(s[s["pnl_net"] <= 0]["pnl_net"].sum())
            return w / l if l > 0 else np.nan

        tot_wr = (subset['realized_r'] > 0).mean() * 100 if len(subset) else 0.0
        tot_exp = subset['realized_r'].mean() if len(subset) else 0.0
        tot_pf = pf(subset) if len(subset) else 0.0
        tot_pnl = subset['pnl_net'].sum() if len(subset) else 0.0

        w1_wr = (w1['realized_r'] > 0).mean() * 100 if len(w1) else 0.0
        w1_exp = w1['realized_r'].mean() if len(w1) else 0.0
        w1_pf = pf(w1) if len(w1) else 0.0
        w1_pnl = w1['pnl_net'].sum() if len(w1) else 0.0

        w2_wr = (w2['realized_r'] > 0).mean() * 100 if len(w2) else 0.0
        w2_exp = w2['realized_r'].mean() if len(w2) else 0.0
        w2_pf = pf(w2) if len(w2) else 0.0
        w2_pnl = w2['pnl_net'].sum() if len(w2) else 0.0

        print(f"\n>>> {name} <<<")
        print(f"  TOTAL:  Trades = {len(subset):3d} | Win Rate = {tot_wr:5.1f}% | Expectancy = {tot_exp:+6.3f}R | Profit Factor = {tot_pf:5.2f} | Net P&L = INR {tot_pnl:+10,.0f}")
        print(f"  W1:     Trades = {len(w1):3d} | Win Rate = {w1_wr:5.1f}% | Expectancy = {w1_exp:+6.3f}R | Profit Factor = {w1_pf:5.2f} | Net P&L = INR {w1_pnl:+10,.0f}")
        print(f"  W2:     Trades = {len(w2):3d} | Win Rate = {w2_wr:5.1f}% | Expectancy = {w2_exp:+6.3f}R | Profit Factor = {w2_pf:5.2f} | Net P&L = INR {w2_pnl:+10,.0f}")

    # Baseline
    print_metrics("0. BASELINE (Current Strategy, No Additional Selection Filter)", df)

    # Hypothesis 1: Volume Breakout Expansion
    print_metrics("1A. HYPOTHESIS 1A: Volume Expansion >= 1.25x 20-day Average", df[df["vol_mult"] >= 1.25])
    print_metrics("1B. HYPOTHESIS 1B: Volume Expansion >= 1.50x 20-day Average", df[df["vol_mult"] >= 1.50])

    # Hypothesis 2: Tighter Gap-Up Limit
    print_metrics("2A. HYPOTHESIS 2A: Tighter Gap-Up Limit (<= 1.5% Gap at Open)", df[df["gap_pct"] <= 1.5])
    print_metrics("2B. HYPOTHESIS 2B: Strict Gap-Up Limit (<= 1.0% Gap at Open)", df[df["gap_pct"] <= 1.0])

    # Hypothesis 3: High Relative Strength (Top Momentum)
    print_metrics("3A. HYPOTHESIS 3A: Top 3-Month RS Return (>= 15% 3-Month Gain)", df[df["rs_3m"] >= 15.0])
    print_metrics("3B. HYPOTHESIS 3B: Top 3-Month RS Return (>= 25% 3-Month Gain)", df[df["rs_3m"] >= 25.0])

    # Hypothesis 4: Nifty Trending Concordance (Slope > 0 & Nifty > SMA50 > SMA200)
    print_metrics("4. HYPOTHESIS 4: Confirmed Trend Concordance (Nifty SMA200 Rising & 50 > 200)", df[df["n_bull"] == True])

    # Combined Selection Models
    comb_1 = (df["vol_mult"] >= 1.25) & (df["gap_pct"] <= 1.5)
    print_metrics("5. COMBINED 1: Volume >= 1.25x AND Gap <= 1.5%", df[comb_1])

    comb_2 = (df["vol_mult"] >= 1.25) & (df["gap_pct"] <= 1.5) & (df["rs_3m"] >= 15.0)
    print_metrics("6. COMBINED 2: Volume >= 1.25x AND Gap <= 1.5% AND RS >= 15%", df[comb_2])

    comb_3 = (df["vol_mult"] >= 1.25) & (df["gap_pct"] <= 1.5) & (df["n_bull"] == True)
    print_metrics("7. COMBINED 3 (High Conviction): Volume >= 1.25x AND Gap <= 1.5% AND Trend Concordance", df[comb_3])

    print("\n" + "=" * 85)
    print("        HYPOTHESES EVALUATION COMPLETE")
    print("=" * 85 + "\n")


if __name__ == "__main__":
    run_evaluation()
