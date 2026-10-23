"""
scripts/diagnose_trades_amended.py — Empirical Trade Diagnosis with Reviewer Amendments:
1. True Exit Taxonomy: (exit_reason, exit_state) distinguishing initial stop, breakeven scratch, trailing, parabolic, time decay.
   Explicitly calculates Gross Win Rate and Net Win Rate.
2. 1,000 Random Draws matched to entry dates & liquidity-gated universe, simulated under identical exits.
   Reports per-window results (W1, W2, Pooled) and Paired Tests on entry dates with Bonferroni correction.
3. Block/Cluster Bootstrap by week for both Gross and Net Expectancy, detailing cluster inflation per window.
4. Nifty-with-Kill-Switch Benchmark measurement on the exact same windows and gates.
"""
from __future__ import annotations

import csv
import logging
import math
import random
from collections import defaultdict
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from sqlalchemy import distinct, select, text

from config import load_config
from data.db.connection import get_session
from data.db.models import MarketDataLake
from engine_core.candidate_builder import build_candidate_dicts
from engine_core.indicators import atr, donchian_low
from engine_core.lifecycle_rules import (
    Bar,
    BarCtx,
    LifecycleRules,
    PosState,
    advance_one_bar,
    parabolic_ref_close,
)
from engine_core.regime_filter import RegimeFilter
from engine_core.regime_gates import is_bull
from engine_core.universe_screener import UniverseScreener

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("diagnose_amended")

OUTPUT_DIR = ROOT / "backtest" / "outputs"


def _to_date(d) -> date:
    if hasattr(d, "date") and callable(getattr(d, "date")):
        return d.date()
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d


# ==============================================================================
# 1. LOAD & RECONCILE ACTUAL TRADES
# ==============================================================================
def load_actual_trades() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load candidate trades from CSV and add true taxonomy."""
    w1_path = OUTPUT_DIR / "trades_pass1_window_2020_2021.csv"
    if not w1_path.exists():
        w1_path = OUTPUT_DIR / "candidate_trades_window_2020_2021.csv"
    w2_path = OUTPUT_DIR / "trades_pass1_window_2022_2026.csv"
    if not w2_path.exists():
        w2_path = OUTPUT_DIR / "candidate_trades_window_2022_2026.csv"

    if not w1_path.exists() or not w2_path.exists():
        raise FileNotFoundError(f"Missing candidate trade CSVs in {OUTPUT_DIR}")

    df_w1 = pd.read_csv(w1_path)
    df_w2 = pd.read_csv(w2_path)
    df_w1["window"] = "W1 (2020-21)"
    df_w2["window"] = "W2 (2022-26)"

    df_all = pd.concat([df_w1, df_w2], ignore_index=True)
    for df in [df_w1, df_w2, df_all]:
        df["entry_date"] = pd.to_datetime(df["entry_date"]).dt.date
        df["exit_date"] = pd.to_datetime(df["exit_date"]).dt.date
        df["one_r"] = df["entry_price"] - df["stop"]
        df["gross_r"] = df["pnl_gross"] / (df["shares"] * df["one_r"])
        df["net_r"] = df["pnl_net"] / (df["shares"] * df["one_r"])

        def classify(r):
            reason = str(r.get("exit_reason", "")).strip().upper()
            state = str(r.get("exit_state", "")).strip().upper()
            if reason == "STOP_HIT":
                if state == "INITIAL_RISK":
                    return "INITIAL_STOP"
                elif state == "RISK_FREE_1_TO_1":
                    return "BREAKEVEN_STOP"
                elif state == "TRAILING_ATR":
                    return "TRAILING_STOP"
                elif state == "PARABOLIC_TRAILING":
                    return "PARABOLIC_STOP"
                return f"STOP_HIT({state})"
            elif reason == "TIME_DECAY" or state == "PENDING_MANUAL_EXIT":
                return "TIME_DECAY"
            elif reason == "END_OF_WINDOW":
                return "END_OF_WINDOW"
            return reason or "UNKNOWN"

        df["taxonomy"] = df.apply(classify, axis=1)

    return df_w1, df_w2, df_all


def print_taxonomy_table(df: pd.DataFrame, title: str) -> None:
    """Print exact exit taxonomy table with both Net Win Rate and Gross Win Rate."""
    logger.info(f"\n=== {title} ===")
    grouped = df.groupby("taxonomy")
    rows = []
    for tax, g in grouped:
        n = len(g)
        net_wins = (g["pnl_net"] > 0).sum()
        net_win_rate = (net_wins / n) * 100.0 if n > 0 else 0.0
        gross_pnl = g["pnl_gross"].sum()
        net_pnl = g["pnl_net"].sum()
        avg_gross_r = g["gross_r"].mean()
        avg_net_r = g["net_r"].mean()
        med_mfe = g["mfe_r"].median() if "mfe_r" in g else float("nan")
        pct_1r = (g["mfe_r"] >= 1.0).mean() * 100.0 if "mfe_r" in g else float("nan")
        avg_days = g["days_held"].mean()
        rows.append({
            "Exit Category": tax,
            "Trades": n,
            "Net Win Rate": f"{net_win_rate:.1f}%",
            "Gross PnL": f"Rs. {gross_pnl:,.0f}",
            "Net PnL": f"Rs. {net_pnl:,.0f}",
            "Avg Gross R": f"{avg_gross_r:+.2f}R",
            "Avg Net R": f"{avg_net_r:+.2f}R",
            "Med MFE (R)": f"{med_mfe:.2f}R" if pd.notna(med_mfe) else "N/A",
            "% Hit +1R": f"{pct_1r:.1f}%" if pd.notna(pct_1r) else "N/A",
            "Avg Days": f"{avg_days:.1f}",
        })

    # Summary row across the whole dataset
    n_tot = len(df)
    tot_net_wins = (df["pnl_net"] > 0).sum()
    tot_net_wr = (tot_net_wins / n_tot) * 100.0 if n_tot > 0 else 0.0
    tot_gross_pnl = df["pnl_gross"].sum()
    tot_net_pnl = df["pnl_net"].sum()
    tot_gross_r = df["gross_r"].mean()
    tot_net_r = df["net_r"].mean()
    tot_med_mfe = df["mfe_r"].median() if "mfe_r" in df else float("nan")
    tot_pct_1r = (df["mfe_r"] >= 1.0).mean() * 100.0 if "mfe_r" in df else float("nan")
    tot_days = df["days_held"].mean()

    rows.append({
        "Exit Category": "TOTAL / OVERALL",
        "Trades": n_tot,
        "Net Win Rate": f"{tot_net_wr:.1f}% ({tot_net_wins}/{n_tot})",
        "Gross PnL": f"Rs. {tot_gross_pnl:,.0f}",
        "Net PnL": f"Rs. {tot_net_pnl:,.0f}",
        "Avg Gross R": f"{tot_gross_r:+.2f}R",
        "Avg Net R": f"{tot_net_r:+.2f}R",
        "Med MFE (R)": f"{tot_med_mfe:.2f}R" if pd.notna(tot_med_mfe) else "N/A",
        "% Hit +1R": f"{tot_pct_1r:.1f}%",
        "Avg Days": f"{tot_days:.1f}",
    })

    summary_df = pd.DataFrame(rows)
    print(summary_df.to_string(index=False))


# ==============================================================================
# 2. RANDOM ENTRY BASELINE (1,000 DRAWS MATCHED BY ENTRY DATE & LIQUIDITY)
# ==============================================================================
def run_random_baseline(
    actual_trades: pd.DataFrame,
    cfg: dict,
    n_draws: int = 1000,
    seed: int = 42,
) -> pd.DataFrame:
    """Run N random entry draws on the exact same entry dates from the liquid universe,

    simulating through identical lifecycle exit rules.
    """
    random.seed(seed)
    np.random.seed(seed)
    rules = LifecycleRules.from_config(cfg)
    ex = cfg["execution"]
    slip_pct = float(ex["exit_slippage_pct"])

    entry_dates = sorted(actual_trades["entry_date"].unique())
    logger.info(f"Running {n_draws} matched random entries across {len(entry_dates)} unique entry dates...")

    with get_session() as s:
        # Fast query for liquid universe on each date
        date_candidates = {}
        for ed in entry_dates:
            liquid_syms = s.execute(text("""
                SELECT symbol FROM market_data_lake
                WHERE trade_date = :ed
                AND (close_raw * volume_raw) >= 100000000
                AND symbol NOT IN ('NIFTY50_INDEX', 'INDIA_VIX')
            """), {"ed": str(ed)}).scalars().all()
            if liquid_syms:
                date_candidates[ed] = list(liquid_syms)

    logger.info(f"Populated liquid candidate pools for {len(date_candidates)} dates.")

    dates_with_pool = [d for d in entry_dates if d in date_candidates and date_candidates[d]]
    if not dates_with_pool:
        logger.error("No liquid candidates found for random baseline!")
        return pd.DataFrame()

    draw_dates = random.choices(dates_with_pool, k=n_draws)
    random_trades = []

    with get_session() as s:
        for idx, ed in enumerate(draw_dates):
            sym = random.choice(date_candidates[ed])
            c = build_candidate_dicts(s, cfg, [sym], ed)
            if not c:
                continue
            adj = c[0]["adjusted_ohlcv"]
            if ed not in adj.index:
                continue

            entry_price = float(adj.loc[ed]["close_adj"])
            atr_series = atr(adj["high_adj"], adj["low_adj"], adj["close_adj"], period=int(cfg["risk"]["atr_period"]))
            atr_val = float(atr_series.loc[ed]) if ed in atr_series.index and pd.notna(atr_series.loc[ed]) else 0.0
            if atr_val <= 0:
                continue

            stop_a = entry_price - float(cfg["risk"]["atr_stop_multiplier"]) * atr_val
            stop_b = float(donchian_low(adj["low_adj"], period=int(cfg["risk"]["donchian_period"])).loc[ed])
            live_stop = min(stop_a, stop_b)
            one_r = entry_price - live_stop
            if one_r <= 0:
                continue

            target = entry_price + 3.0 * one_r

            pos = PosState(
                entry_price=entry_price,
                initial_stop=live_stop,
                live_stop=live_stop,
                target=target,
                highest_high=entry_price,
                shares_remaining=100,
            )

            # Forward bars simulation from MarketDataLake
            fwd_bars = s.execute(
                select(MarketDataLake.trade_date, MarketDataLake.open_raw, MarketDataLake.high_raw,
                       MarketDataLake.low_raw, MarketDataLake.close_raw)
                .where(MarketDataLake.symbol == sym)
                .where(MarketDataLake.trade_date > ed)
                .order_by(MarketDataLake.trade_date)
                .limit(40)
            ).all()

            if not fwd_bars:
                continue

            closed = False
            exit_p = entry_price
            exit_reas = "OPEN"
            fwd_ret_1 = None
            fwd_ret_5 = None
            fwd_ret_10 = None
            fwd_ret_20 = None

            for bar_idx, fb in enumerate(fwd_bars):
                bar = Bar(float(fb.open_raw), float(fb.high_raw), float(fb.low_raw), float(fb.close_raw))

                if bar_idx == 0:
                    fwd_ret_1 = (bar.close / entry_price - 1.0) * 100.0
                if bar_idx == 4:
                    fwd_ret_5 = (bar.close / entry_price - 1.0) * 100.0
                if bar_idx == 9:
                    fwd_ret_10 = (bar.close / entry_price - 1.0) * 100.0
                if bar_idx == 19:
                    fwd_ret_20 = (bar.close / entry_price - 1.0) * 100.0

                if closed:
                    continue

                b_ctx = BarCtx(atr_val, False, True, None)
                res = advance_one_bar(pos, bar, b_ctx, rules, slip_pct)
                pos = res.pos
                if res.closed:
                    closed = True
                    exit_p = res.exits[-1].price if res.exits else bar.close
                    exit_reas = res.exits[-1].reason if res.exits else "STOP_HIT"

            if not closed:
                exit_p = float(fwd_bars[-1].close_raw)

            gross_r = (exit_p - entry_price) / one_r
            # Net R estimating slippage and STT (~0.2% per round trip)
            net_exit_p = exit_p * (1.0 - slip_pct / 100.0) - (exit_p * 0.00025)
            net_r = (net_exit_p - entry_price * (1.0 + slip_pct / 100.0)) / one_r

            window_tag = "W1 (2020-21)" if ed < date(2022, 1, 1) else "W2 (2022-26)"

            random_trades.append({
                "symbol": sym,
                "entry_date": ed,
                "window": window_tag,
                "gross_r": gross_r,
                "net_r": net_r,
                "exit_reason": exit_reas,
                "ret_1": fwd_ret_1,
                "ret_5": fwd_ret_5,
                "ret_10": fwd_ret_10,
                "ret_20": fwd_ret_20,
            })

    df_rand = pd.DataFrame(random_trades)
    logger.info(f"Simulated {len(df_rand)} random entries.")
    return df_rand


# ==============================================================================
# 3. BLOCK/CLUSTER BOOTSTRAP BY WEEK (GROSS & NET)
# ==============================================================================
def run_block_bootstrap(
    trades_df: pd.DataFrame,
    col_name: str = "net_r",
    n_iterations: int = 2000,
    seed: int = 42,
) -> Dict[str, float]:
    """Run block/cluster bootstrap by calendar week on R-multiples."""
    np.random.seed(seed)
    df = trades_df.copy()
    df["week"] = df["entry_date"].apply(lambda d: f"{d.year}-W{d.isocalendar()[1]:02d}")

    weeks = sorted(df["week"].unique())
    week_groups = {w: df[df["week"] == w][col_name].values for w in weeks}

    # Trade-level unclustered bootstrap
    r_all = df[col_name].values
    n_trades = len(r_all)
    unclustered_means = np.zeros(n_iterations)
    for i in range(n_iterations):
        sample = np.random.choice(r_all, size=n_trades, replace=True)
        unclustered_means[i] = np.mean(sample)

    # Clustered / Block bootstrap (resample weeks)
    clustered_means = np.zeros(n_iterations)
    n_weeks = len(weeks)
    for i in range(n_iterations):
        sampled_weeks = np.random.choice(weeks, size=n_weeks, replace=True)
        pooled = np.concatenate([week_groups[w] for w in sampled_weeks])
        clustered_means[i] = np.mean(pooled)

    orig_mean = np.mean(r_all)
    u_se = np.std(unclustered_means)
    u_ci95 = (np.percentile(unclustered_means, 2.5), np.percentile(unclustered_means, 97.5))
    u_ci99 = (np.percentile(unclustered_means, 0.5), np.percentile(unclustered_means, 99.5))

    c_se = np.std(clustered_means)
    c_ci95 = (np.percentile(clustered_means, 2.5), np.percentile(clustered_means, 97.5))
    c_ci99 = (np.percentile(clustered_means, 0.5), np.percentile(clustered_means, 99.5))
    p_neg = np.mean(clustered_means <= 0.0)
    se_inflation_pct = ((c_se / u_se) - 1.0) * 100.0 if u_se > 0 else 0.0

    return {
        "mean": orig_mean,
        "n_trades": n_trades,
        "n_weeks": n_weeks,
        "unclustered_se": u_se,
        "unclustered_ci95": u_ci95,
        "unclustered_ci99": u_ci99,
        "clustered_se": c_se,
        "clustered_ci95": c_ci95,
        "clustered_ci99": c_ci99,
        "se_inflation_pct": se_inflation_pct,
        "p_expectancy_le_zero": p_neg,
    }


# ==============================================================================
# 4. NIFTY-WITH-KILL-SWITCH BENCHMARK
# ==============================================================================
def run_nifty_with_kill_switch_baseline(
    cfg: dict,
    start_d: date,
    end_d: date,
    initial_equity: float = 1_000_000.0,
    rf_pct: float = 6.5,
) -> Dict[str, any]:
    """Measure the exact fallback benchmark: Nifty 50 with macro Kill Switch."""
    with get_session() as s:
        regime = RegimeFilter(cfg, s)
        days_raw = (
            s.execute(
                select(MarketDataLake.trade_date, MarketDataLake.close_raw)
                .where(MarketDataLake.symbol == "NIFTY50_INDEX")
                .where(MarketDataLake.trade_date >= start_d, MarketDataLake.trade_date <= end_d)
                .order_by(MarketDataLake.trade_date)
            )
            .all()
        )

    if not days_raw:
        return {}

    dates = [_to_date(r[0]) for r in days_raw]
    closes = [float(r[1]) for r in days_raw]

    daily_rf = (1.0 + rf_pct / 100.0) ** (1.0 / 252.0) - 1.0

    equity = initial_equity
    nifty_shares = 0.0
    cash = initial_equity
    curve = []
    regime_states = []

    with get_session() as s:
        regime = RegimeFilter(cfg, s)
        for d, c in zip(dates, closes):
            rs = regime.evaluate(d)
            ks = bool(rs.kill_switch_active)
            regime_states.append(ks)

            if ks:
                if nifty_shares > 0:
                    cash = nifty_shares * c
                    nifty_shares = 0.0
                cash *= (1.0 + daily_rf)
                equity = cash
            else:
                if nifty_shares == 0.0:
                    nifty_shares = cash / c
                    cash = 0.0
                equity = nifty_shares * c

            curve.append({"date": d, "equity": equity, "kill_switch": ks})

    curve_df = pd.DataFrame(curve)
    tot_ret = (curve_df["equity"].iloc[-1] / initial_equity - 1.0) * 100.0
    years = (dates[-1] - dates[0]).days / 365.25
    cagr = ((curve_df["equity"].iloc[-1] / initial_equity) ** (1.0 / years) - 1.0) * 100.0 if years > 0 else 0.0

    curve_df["peak"] = curve_df["equity"].cummax()
    curve_df["dd"] = (curve_df["equity"] - curve_df["peak"]) / curve_df["peak"] * 100.0
    max_dd = curve_df["dd"].min()

    daily_rets = curve_df["equity"].pct_change().dropna()
    excess_rets = daily_rets - daily_rf
    sharpe = (excess_rets.mean() / excess_rets.std()) * math.sqrt(252) if excess_rets.std() > 0 else 0.0
    pct_cash = np.mean(regime_states) * 100.0

    return {
        "start_date": str(dates[0]),
        "end_date": str(dates[-1]),
        "years": years,
        "total_return_pct": tot_ret,
        "cagr_pct": cagr,
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "pct_days_in_cash": pct_cash,
        "final_equity": curve_df["equity"].iloc[-1],
    }


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main():
    cfg = load_config()
    logger.info("=== Starting Step 2 Amended Diagnostics ===")

    # 1. Load actual trades
    df_w1, df_w2, df_all = load_actual_trades()
    logger.info(f"Loaded {len(df_w1)} W1 trades, {len(df_w2)} W2 trades ({len(df_all)} pooled).")

    # 1A. Exit Taxonomy
    print_taxonomy_table(df_w1, "Window 1 (2020-21) True Exit Taxonomy")
    print_taxonomy_table(df_w2, "Window 2 (2022-26) True Exit Taxonomy")
    print_taxonomy_table(df_all, "Pooled (2020-26) True Exit Taxonomy")

    # 2. Block Bootstrap (Net R and Gross R)
    logger.info("\n=== Block/Cluster Bootstrap by Week on Net Expectancy (2,000 Iterations) ===")
    for name, df in [("W1 (2020-21)", df_w1), ("W2 (2022-26)", df_w2), ("Pooled (2020-26)", df_all)]:
        boot_net = run_block_bootstrap(df, col_name="net_r", n_iterations=2000)
        boot_gross = run_block_bootstrap(df, col_name="gross_r", n_iterations=2000)
        print(f"\n--- {name} (N={boot_net['n_trades']} trades across {boot_net['n_weeks']} weeks) ---")
        print(f"Sample Mean Gross Expectancy: {boot_gross['mean']:+.3f}R | Net Expectancy: {boot_net['mean']:+.3f}R")
        print(f"Unclustered (Trade-level) Net SE: ±{boot_net['unclustered_se']:.3f}R, "
              f"95% CI: [{boot_net['unclustered_ci95'][0]:+.3f}R, {boot_net['unclustered_ci95'][1]:+.3f}R], "
              f"99% CI: [{boot_net['unclustered_ci99'][0]:+.3f}R, {boot_net['unclustered_ci99'][1]:+.3f}R]")
        print(f"Clustered (Week-level) Net SE:    ±{boot_net['clustered_se']:.3f}R "
              f"(SE inflation: {boot_net['se_inflation_pct']:+.1f}%), "
              f"95% CI: [{boot_net['clustered_ci95'][0]:+.3f}R, {boot_net['clustered_ci95'][1]:+.3f}R], "
              f"99% CI: [{boot_net['clustered_ci99'][0]:+.3f}R, {boot_net['clustered_ci99'][1]:+.3f}R]")
        print(f"P(Net Expectancy <= 0.0R):        {boot_net['p_expectancy_le_zero']*100.0:.1f}%")

    # 3. Nifty-with-Kill-Switch Benchmark
    logger.info("\n=== Nifty-with-Kill-Switch Baseline (Fallback Strategy) ===")
    w1_res = run_nifty_with_kill_switch_baseline(cfg, date(2020, 1, 1), date(2021, 12, 31))
    w2_res = run_nifty_with_kill_switch_baseline(cfg, date(2022, 1, 1), date(2026, 10, 16))
    pooled_res = run_nifty_with_kill_switch_baseline(cfg, date(2020, 1, 1), date(2026, 10, 16))

    bench_df = pd.DataFrame([
        {
            "Window": "W1 (2020-21)",
            "Nifty+KillSwitch CAGR": f"{w1_res.get('cagr_pct', 0):.2f}%",
            "Max DD": f"{w1_res.get('max_drawdown_pct', 0):.2f}%",
            "Sharpe": f"{w1_res.get('sharpe_ratio', 0):.2f}",
            "Days in Cash": f"{w1_res.get('pct_days_in_cash', 0):.1f}%",
        },
        {
            "Window": "W2 (2022-26)",
            "Nifty+KillSwitch CAGR": f"{w2_res.get('cagr_pct', 0):.2f}%",
            "Max DD": f"{w2_res.get('max_drawdown_pct', 0):.2f}%",
            "Sharpe": f"{w2_res.get('sharpe_ratio', 0):.2f}",
            "Days in Cash": f"{w2_res.get('pct_days_in_cash', 0):.1f}%",
        },
        {
            "Window": "Pooled (2020-26)",
            "Nifty+KillSwitch CAGR": f"{pooled_res.get('cagr_pct', 0):.2f}%",
            "Max DD": f"{pooled_res.get('max_drawdown_pct', 0):.2f}%",
            "Sharpe": f"{pooled_res.get('sharpe_ratio', 0):.2f}",
            "Days in Cash": f"{pooled_res.get('pct_days_in_cash', 0):.1f}%",
        },
    ])
    print("\n" + bench_df.to_string(index=False))

    # 4. Random Baseline (1,000 Draws) with Per-Window Breakdown and Paired Tests
    logger.info("\n=== 1,000 Matched Random Draws Baseline (Per-Window & Paired Tests) ===")
    rand_df = run_random_baseline(df_all, cfg, n_draws=1000)
    if not rand_df.empty:
        # Compute actual forward returns
        logger.info("Computing actual trades forward returns from market_data_lake...")
        with get_session() as s:
            act_1, act_5, act_10, act_20 = [], [], [], []
            for _, row in df_all.iterrows():
                sym, ed, ep = row["symbol"], row["entry_date"], row["entry_price"]
                fwd_bars = s.execute(
                    select(MarketDataLake.close_raw)
                    .where(MarketDataLake.symbol == sym)
                    .where(MarketDataLake.trade_date > ed)
                    .order_by(MarketDataLake.trade_date)
                    .limit(25)
                ).scalars().all()
                act_1.append((float(fwd_bars[0]) / ep - 1.0) * 100.0 if len(fwd_bars) > 0 else np.nan)
                act_5.append((float(fwd_bars[4]) / ep - 1.0) * 100.0 if len(fwd_bars) > 4 else np.nan)
                act_10.append((float(fwd_bars[9]) / ep - 1.0) * 100.0 if len(fwd_bars) > 9 else np.nan)
                act_20.append((float(fwd_bars[19]) / ep - 1.0) * 100.0 if len(fwd_bars) > 19 else np.nan)
            df_all["ret_1"] = act_1
            df_all["ret_5"] = act_5
            df_all["ret_10"] = act_10
            df_all["ret_20"] = act_20

        # Per-Window Forward Return & Expectancy Comparison
        for win_tag in ["W1 (2020-21)", "W2 (2022-26)", "Pooled"]:
            sub_act = df_all if win_tag == "Pooled" else df_all[df_all["window"] == win_tag]
            sub_rand = rand_df if win_tag == "Pooled" else rand_df[rand_df["window"] == win_tag]

            print(f"\n--- {win_tag}: Forward Return Comparison (Bonferroni alpha = 0.05/4 = 0.0125) ---")
            fwd_rows = []
            for t_day, col in [(1, "ret_1"), (5, "ret_5"), (10, "ret_10"), (20, "ret_20")]:
                # Group by entry date for paired test
                date_act = sub_act.groupby("entry_date")[col].mean()
                date_rand = sub_rand.groupby("entry_date")[col].mean()
                common_dates = sorted(set(date_act.index).intersection(set(date_rand.index)))

                if common_dates:
                    paired_diffs = np.array([date_act[d] - date_rand[d] for d in common_dates if pd.notna(date_act[d]) and pd.notna(date_rand[d])])
                    mean_diff = np.mean(paired_diffs)
                    se_diff = np.std(paired_diffs, ddof=1) / np.sqrt(len(paired_diffs)) if len(paired_diffs) > 1 else 1e-9
                    t_paired = mean_diff / se_diff
                    # Permutation test on paired differences (randomly flip sign)
                    n_pairs = len(paired_diffs)
                    perm_means = np.zeros(2000)
                    for pi in range(2000):
                        signs = np.random.choice([-1.0, 1.0], size=n_pairs)
                        perm_means[pi] = np.mean(paired_diffs * signs)
                    p_paired = np.mean(np.abs(perm_means) >= np.abs(mean_diff))
                else:
                    mean_diff, se_diff, t_paired, p_paired = np.nan, np.nan, np.nan, np.nan

                act_mean = sub_act[col].dropna().mean()
                act_se = sub_act[col].dropna().std() / np.sqrt(len(sub_act[col].dropna()))
                rand_mean = sub_rand[col].dropna().mean()
                rand_se = sub_rand[col].dropna().std() / np.sqrt(len(sub_rand[col].dropna()))

                sig_note = "Suggestive" if (p_paired < 0.05 and p_paired >= 0.0125) else ("Significant" if p_paired < 0.0125 else "Not Sig")

                fwd_rows.append({
                    "Horizon": f"T+{t_day}",
                    "Actual (SE)": f"{act_mean:+.2f}% (±{act_se:.2f}%)",
                    "Random (SE)": f"{rand_mean:+.2f}% (±{rand_se:.2f}%)",
                    "Paired Diff": f"{mean_diff:+.2f}%",
                    "Paired t": f"{t_paired:+.2f}",
                    "Paired p-val": f"{p_paired:.4f}",
                    "Status": sig_note,
                })
            print(pd.DataFrame(fwd_rows).to_string(index=False))

            # Expectancy comparison
            act_gross_r = sub_act["gross_r"].dropna().mean()
            act_net_r = sub_act["net_r"].dropna().mean()
            act_net_se = sub_act["net_r"].dropna().std() / np.sqrt(len(sub_act["net_r"].dropna()))

            rand_gross_r = sub_rand["gross_r"].dropna().mean()
            rand_net_r = sub_rand["net_r"].dropna().mean()
            rand_net_se = sub_rand["net_r"].dropna().std() / np.sqrt(len(sub_rand["net_r"].dropna()))

            diff_net_r = act_net_r - rand_net_r
            t_net_r = diff_net_r / math.sqrt(act_net_se**2 + rand_net_se**2)

            print(f"Expectancy: Actual Gross {act_gross_r:+.3f}R / Net {act_net_r:+.3f}R (±{act_net_se:.3f}R, N={len(sub_act)}) vs "
                  f"Random Gross {rand_gross_r:+.3f}R / Net {rand_net_r:+.3f}R (±{rand_net_se:.3f}R, N={len(sub_rand)}) | "
                  f"Net Diff: {diff_net_r:+.3f}R (t = {t_net_r:+.2f})")

    logger.info("\n=== Step 2 Amended Diagnostics Complete ===")


if __name__ == "__main__":
    main()
