"""Standalone diagnostic script to measure entry edge, forward drift, and MFE/MAE on existing trades.

Zero changes to core engine. Evaluates the 198 closed trades from Pass 1 backtests.
"""
from __future__ import annotations

import logging
import random
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure project root is in sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
from sqlalchemy import desc, func, select, text

from config import load_config
from data.db.connection import get_session
from data.db.models import MarketDataLake
from engine_core.sector_map import sector_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("diagnose_trades")


def load_all_trades() -> pd.DataFrame:
    """Load and combine trades from both Pass 1 backtest windows."""
    out_dir = _ROOT / "backtest" / "outputs"
    t1_path = out_dir / "trades_pass1_window_2020_2021.csv"
    t2_path = out_dir / "trades_pass1_window_2022_2026.csv"

    df1 = pd.read_csv(t1_path)
    df1["window"] = "window_2020_2021"
    df2 = pd.read_csv(t2_path)
    df2["window"] = "window_2022_2026"

    combined = pd.concat([df1, df2], ignore_index=True)
    combined["entry_date"] = pd.to_datetime(combined["entry_date"]).dt.date
    combined["exit_date"] = pd.to_datetime(combined["exit_date"]).dt.date
    combined["one_r"] = combined["entry_price"] - combined["stop"]
    combined["realized_r"] = combined["pnl_net"] / (combined["one_r"] * combined["shares"])
    combined["sector"] = combined["symbol"].apply(sector_for)
    return combined


def compute_nifty_history(session) -> pd.DataFrame:
    """Pre-fetch Nifty index closes and compute SMA200 and 20-day slope."""
    rows = session.execute(
        select(MarketDataLake.trade_date, MarketDataLake.close_raw)
        .where(MarketDataLake.symbol == "NIFTY50_INDEX")
        .order_by(MarketDataLake.trade_date)
    ).all()
    df = pd.DataFrame(rows, columns=["trade_date", "close"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["sma200"] = df["close"].rolling(200).mean()
    df["sma200_slope_20d"] = (df["sma200"] - df["sma200"].shift(20)) / df["sma200"].shift(20) * 100.0
    return df.set_index("trade_date")


def compute_vix_history(session) -> pd.DataFrame:
    """Pre-fetch India VIX closes."""
    rows = session.execute(
        select(MarketDataLake.trade_date, MarketDataLake.close_raw)
        .where(MarketDataLake.symbol == "INDIA_VIX")
        .order_by(MarketDataLake.trade_date)
    ).all()
    df = pd.DataFrame(rows, columns=["trade_date", "vix_close"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df.set_index("trade_date")


def compute_market_breadth_cache(session) -> dict:
    """Compute market breadth (% of active stocks > 50-day SMA) on trading dates."""
    logger.info("Computing market breadth cache for all trade dates...")
    # Get distinct trade dates of candidate entries
    dates_query = text("""
        SELECT DISTINCT trade_date FROM market_data_lake
        WHERE trade_date >= '2020-01-01' AND trade_date <= '2026-10-01'
        AND symbol NOT IN ('NIFTY50_INDEX', 'INDIA_VIX')
        ORDER BY trade_date
    """)
    all_dates = [date.fromisoformat(str(r[0])) for r in session.execute(dates_query).all()]
    
    # Sample breadth calculation every 5 days or on entry dates
    breadth_map = {}
    # Optimized query: for each sample date, count total and above SMA50
    # To keep it fast, we can approximate market breadth using the 100 most liquid stocks
    top_stocks = [r[0] for r in session.execute(text("""
        SELECT symbol FROM market_data_lake
        WHERE trade_date = '2024-01-01' AND symbol NOT IN ('NIFTY50_INDEX', 'INDIA_VIX')
        ORDER BY volume_raw * close_raw DESC LIMIT 100
    """)).all()]

    if not top_stocks:
        top_stocks = [r[0] for r in session.execute(text("""
            SELECT DISTINCT symbol FROM market_data_lake
            WHERE symbol NOT IN ('NIFTY50_INDEX', 'INDIA_VIX') LIMIT 100
        """)).all()]

    logger.info(f"Using top {len(top_stocks)} benchmark equities for breadth estimation.")
    return breadth_map


def analyze_trades():
    logger.info("=== Loading Closed Trades ===")
    trades_df = load_all_trades()
    logger.info(f"Loaded {len(trades_df)} total closed trades.")

    with get_session() as session:
        nifty_df = compute_nifty_history(session)
        vix_df = compute_vix_history(session)

        # Enhance each trade with forward returns and MFE/MAE
        logger.info("Fetching forward daily bars and computing MFE/MAE for each trade...")
        results = []

        for idx, row in trades_df.iterrows():
            sym = row["symbol"]
            ed = row["entry_date"]
            xd = row["exit_date"]
            ep = row["entry_price"]
            sp = row["stop"]
            one_r = row["one_r"]

            # Query forward 30 sessions for this symbol
            bars = session.execute(
                select(MarketDataLake.trade_date, MarketDataLake.open_raw, MarketDataLake.high_raw,
                       MarketDataLake.low_raw, MarketDataLake.close_raw)
                .where(MarketDataLake.symbol == sym)
                .where(MarketDataLake.trade_date >= ed)
                .order_by(MarketDataLake.trade_date)
                .limit(35)
            ).all()

            if not bars:
                continue

            bar_dates = [b.trade_date for b in bars]
            bar_closes = [float(b.close_raw) for b in bars]
            bar_highs = [float(b.high_raw) for b in bars]
            bar_lows = [float(b.low_raw) for b in bars]

            # Forward returns at T+1, T+5, T+10, T+20
            ret_1d = (bar_closes[1] - ep) / ep * 100.0 if len(bar_closes) > 1 else np.nan
            ret_5d = (bar_closes[5] - ep) / ep * 100.0 if len(bar_closes) > 5 else np.nan
            ret_10d = (bar_closes[10] - ep) / ep * 100.0 if len(bar_closes) > 10 else np.nan
            ret_20d = (bar_closes[20] - ep) / ep * 100.0 if len(bar_closes) > 20 else np.nan

            # MFE and MAE during the actual holding period (between ed and xd)
            holding_bars = [b for b in bars if b.trade_date <= xd]
            if holding_bars and one_r > 0:
                max_high = max(float(b.high_raw) for b in holding_bars)
                min_low = min(float(b.low_raw) for b in holding_bars)
                mfe_r = (max_high - ep) / one_r
                mae_r = (min_low - ep) / one_r
            else:
                mfe_r = np.nan
                mae_r = np.nan

            # Prior day close to measure gap-up at entry
            prior_bar = session.execute(
                select(MarketDataLake.close_raw)
                .where(MarketDataLake.symbol == sym)
                .where(MarketDataLake.trade_date < ed)
                .order_by(desc(MarketDataLake.trade_date))
                .limit(1)
            ).scalar()

            gap_pct = (ep - float(prior_bar)) / float(prior_bar) * 100.0 if prior_bar else np.nan

            # Nifty and VIX macro context
            nifty_row = nifty_df.loc[ed] if ed in nifty_df.index else None
            n_slope = float(nifty_row["sma200_slope_20d"]) if nifty_row is not None and pd.notna(nifty_row.get("sma200_slope_20d")) else np.nan
            n_above_sma = (ep > float(nifty_row["sma200"])) if nifty_row is not None and pd.notna(nifty_row.get("sma200")) else None

            vix_val = float(vix_df.loc[ed]["vix_close"]) if ed in vix_df.index else np.nan

            # Classify exit reason
            if row["days_held"] >= 20 and abs(row["pnl_net"]) < row["one_r"] * row["shares"] * 0.5:
                exit_cat = "TIME_DECAY"
            elif row["realized_r"] <= -0.7:
                exit_cat = "STOP_HIT"
            elif row["realized_r"] >= 0.7:
                exit_cat = "PROFIT_EXIT"
            else:
                exit_cat = "BREAKEVEN_SCRATCH"

            res_dict = dict(row)
            res_dict.update({
                "ret_1d_pct": ret_1d,
                "ret_5d_pct": ret_5d,
                "ret_10d_pct": ret_10d,
                "ret_20d_pct": ret_20d,
                "mfe_r": mfe_r,
                "mae_r": mae_r,
                "gap_pct": gap_pct,
                "nifty_sma200_slope": n_slope,
                "vix_at_entry": vix_val,
                "exit_cat": exit_cat,
            })
            results.append(res_dict)

    res_df = pd.DataFrame(results)

    # -------------------------------------------------------------
    # PRINT COMPREHENSIVE DIAGNOSTIC REPORT
    # -------------------------------------------------------------
    print("\n" + "=" * 80)
    print("      STOCKBOT EMPIRICAL EDGE DIAGNOSTIC REPORT (198 CLOSED TRADES)")
    print("=" * 80)

    print("\n--- 1. Post-Entry Forward Price Drift (Does the Entry Have Edge?) ---")
    for w in ["window_2020_2021", "window_2022_2026", "ALL"]:
        sub = res_df if w == "ALL" else res_df[res_df["window"] == w]
        print(f"\n[{w}] (N = {len(sub)} trades):")
        print(f"  T+1 Day Drift:   mean = {sub['ret_1d_pct'].mean():+.2f}%, median = {sub['ret_1d_pct'].median():+.2f}% | Win Rate = {(sub['ret_1d_pct'] > 0).mean() * 100:.1f}%")
        print(f"  T+5 Day Drift:   mean = {sub['ret_5d_pct'].mean():+.2f}%, median = {sub['ret_5d_pct'].median():+.2f}% | Win Rate = {(sub['ret_5d_pct'] > 0).mean() * 100:.1f}%")
        print(f"  T+10 Day Drift:  mean = {sub['ret_10d_pct'].mean():+.2f}%, median = {sub['ret_10d_pct'].median():+.2f}% | Win Rate = {(sub['ret_10d_pct'] > 0).mean() * 100:.1f}%")
        print(f"  T+20 Day Drift:  mean = {sub['ret_20d_pct'].mean():+.2f}%, median = {sub['ret_20d_pct'].median():+.2f}% | Win Rate = {(sub['ret_20d_pct'] > 0).mean() * 100:.1f}%")

    print("\n--- 2. Maximum Favorable (MFE) vs. Maximum Adverse Excursion (MAE) ---")
    for w in ["window_2020_2021", "window_2022_2026", "ALL"]:
        sub = res_df if w == "ALL" else res_df[res_df["window"] == w]
        pct_hit_1r = (sub["mfe_r"] >= 1.0).mean() * 100
        pct_hit_2r = (sub["mfe_r"] >= 2.0).mean() * 100
        pct_hit_3r = (sub["mfe_r"] >= 3.0).mean() * 100
        print(f"\n[{w}]:")
        print(f"  Avg MFE (Peak Profit Reached): +{sub['mfe_r'].mean():.2f}R (median +{sub['mfe_r'].median():.2f}R)")
        print(f"  Avg MAE (Max Drawdown Dip):    {sub['mae_r'].mean():.2f}R (median {sub['mae_r'].median():.2f}R)")
        print(f"  Trades reaching >= +1.0R:      {pct_hit_1r:.1f}% ({int(pct_hit_1r * len(sub) / 100)}/{len(sub)})")
        print(f"  Trades reaching >= +2.0R:      {pct_hit_2r:.1f}% ({int(pct_hit_2r * len(sub) / 100)}/{len(sub)})")
        print(f"  Trades reaching >= +3.0R:      {pct_hit_3r:.1f}% ({int(pct_hit_3r * len(sub) / 100)}/{len(sub)})")

    print("\n--- 3. Performance by Nifty 200 SMA Slope at Entry ---")
    res_df["slope_regime"] = pd.cut(
        res_df["nifty_sma200_slope"],
        bins=[-99, 0.0, 1.0, 99],
        labels=["Flat/Falling (<0%)", "Mildly Rising (0-1%)", "Strongly Rising (>1%)"]
    )
    slope_grp = res_df.groupby("slope_regime", observed=False).agg(
        trades=("symbol", "count"),
        win_rate=("realized_r", lambda s: (s > 0).mean() * 100),
        avg_r=("realized_r", "mean"),
        total_pnl=("pnl_net", "sum"),
    )
    print(slope_grp.to_string())

    print("\n--- 4. Performance by Entry Gap Size ---")
    res_df["gap_bracket"] = pd.cut(
        res_df["gap_pct"],
        bins=[-99, 0.5, 1.5, 3.0, 99],
        labels=["Flat/Dip (<0.5%)", "Moderate Gap (0.5-1.5%)", "Large Gap (1.5-3.0%)", "Excessive Gap (>3.0%)"]
    )
    gap_grp = res_df.groupby("gap_bracket", observed=False).agg(
        trades=("symbol", "count"),
        win_rate=("realized_r", lambda s: (s > 0).mean() * 100),
        avg_r=("realized_r", "mean"),
        avg_mfe=("mfe_r", "mean"),
    )
    print(gap_grp.to_string())

    print("\n--- 5. Exit Category Breakdown ---")
    exit_grp = res_df.groupby(["window", "exit_cat"]).agg(
        trades=("symbol", "count"),
        avg_r=("realized_r", "mean"),
        total_pnl=("pnl_net", "sum"),
        avg_days=("days_held", "mean"),
    )
    print(exit_grp.to_string())

    print("\n--- 6. Comparison with Benchmark Random Entry (Same Universe & Dates) ---")
    # Simulate 500 random entries across the same date range
    random.seed(42)
    with get_session() as session:
        random_dates = random.choices(list(trades_df["entry_date"]), k=300)
        random_syms = random.choices(list(trades_df["symbol"].unique()), k=300)
        rnd_rets_5d = []
        rnd_rets_20d = []
        for r_sym, r_d in zip(random_syms, random_dates):
            r_bars = session.execute(
                select(MarketDataLake.close_raw)
                .where(MarketDataLake.symbol == r_sym)
                .where(MarketDataLake.trade_date >= r_d)
                .order_by(MarketDataLake.trade_date)
                .limit(22)
            ).scalars().all()
            if len(r_bars) >= 6:
                rnd_rets_5d.append((float(r_bars[5]) - float(r_bars[0])) / float(r_bars[0]) * 100)
            if len(r_bars) >= 21:
                rnd_rets_20d.append((float(r_bars[20]) - float(r_bars[0])) / float(r_bars[0]) * 100)

        rnd_5d_mean = np.mean(rnd_rets_5d) if rnd_rets_5d else 0.0
        rnd_20d_mean = np.mean(rnd_rets_20d) if rnd_rets_20d else 0.0
        strat_5d_mean = res_df["ret_5d_pct"].mean()
        strat_20d_mean = res_df["ret_20d_pct"].mean()

        print(f"Random Entries (N=300):    T+5 Return = {rnd_5d_mean:+.2f}% | T+20 Return = {rnd_20d_mean:+.2f}%")
        print(f"Strategy Entries (N=198):  T+5 Return = {strat_5d_mean:+.2f}% | T+20 Return = {strat_20d_mean:+.2f}%")
        print(f"Alpha over Random Entry:   T+5 Alpha  = {strat_5d_mean - rnd_5d_mean:+.2f}% | T+20 Alpha  = {strat_20d_mean - rnd_20d_mean:+.2f}%")

    print("\n" + "=" * 80)
    print("      DIAGNOSTIC MEASUREMENT COMPLETE")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    analyze_trades()
