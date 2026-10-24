"""
scripts/redesigned_random_baseline.py — Rigorous Apples-to-Apples Random Baseline:
1. Universe: Same screened pool on signal date T (Gates 1-3: Mcap > 5000cr, ADTV > 25cr, Age > 252) AND Trend Filter (Close > SMA50 > SMA200).
2. Execution: Enters at T+1 Open with 0.10% entry slippage, enforces <= 3.0% gap cap, verifies RR >= 1.5 at fill.
3. Sizing & Exits: Exact same risk sizing (1% risk) and lifecycle exits via advance_one_bar() with 0.10% exit slippage.
4. Output: Trade-level pairing against actual trades, paired t-tests, date-clustered SEs, and permutation p-values.
"""
from __future__ import annotations

import logging
import math
import random
import sys
sys.stdout.reconfigure(encoding='utf-8')
from collections import defaultdict
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
from engine_core.costs import CostModel
from engine_core.entry_filters import passes_trend_filter
from engine_core.indicators import atr, donchian_high, donchian_low
from engine_core.lifecycle_rules import (
    Bar,
    BarCtx,
    LifecycleRules,
    PosState,
    advance_one_bar,
    parabolic_ref_close,
    plan_entry_fill,
)
from engine_core.universe_screener import UniverseScreener

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("redesigned_baseline")

OUTPUT_DIR = ROOT / "backtest" / "outputs"


def _to_date(d) -> date:
    if hasattr(d, "date") and callable(getattr(d, "date")):
        return d.date()
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d


def load_actual_trades(session) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    w1_path = OUTPUT_DIR / "trades_pass1_window_2020_2021.csv"
    w2_path = OUTPUT_DIR / "trades_pass1_window_2022_2026.csv"
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
        df["unique_trade_id"] = df["window"].astype(str) + "_" + df["position_id"].astype(str)

    # Compute actual trade forward returns from fill price on sessions AFTER entry (trade_date > ed)
    for h in [1, 5, 10, 20]:
        rets = []
        for _, r in df_all.iterrows():
            sym, ed, ep = r["symbol"], r["entry_date"], r["entry_price"]
            bars = session.execute(
                select(MarketDataLake.close_raw)
                .where(MarketDataLake.symbol == sym, MarketDataLake.trade_date > ed)
                .order_by(MarketDataLake.trade_date)
                .limit(h)
            ).scalars().all()
            if len(bars) >= h:
                rets.append((float(bars[-1]) / ep - 1.0) * 100.0)
            else:
                rets.append(np.nan)
        df_all[f"ret_{h}"] = rets

    # Re-slice w1 and w2 from df_all
    df_w1 = df_all[df_all["window"] == "W1 (2020-21)"].copy()
    df_w2 = df_all[df_all["window"] == "W2 (2022-26)"].copy()
    return df_w1, df_w2, df_all


def build_screened_trend_pools(cfg: dict, signal_dates: List[date], session) -> Dict[date, List[str]]:
    """Build and cache the exact qualified universe on signal date T:
    Gates 1-3 + Trend Filter (Close > SMA50 > SMA200).
    """
    import json
    cache_path = OUTPUT_DIR / "screened_trend_pools.json"
    if cache_path.exists():
        logger.info(f"Loading cached screened trend pools from {cache_path}...")
        with open(cache_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {date.fromisoformat(k): v for k, v in raw.items()}

    screener = UniverseScreener(cfg, session)
    ef = cfg.get("entry_filters", {})
    fast_sma = int(ef.get("trend_fast_sma", 50))
    slow_sma = int(ef.get("trend_slow_sma", 200))

    pools = {}
    logger.info(f"Screening qualified trend universe across {len(signal_dates)} unique signal dates...")

    for idx, sd in enumerate(signal_dates):
        # Pre-filter to actively trading symbols with turnover >= 1cr (ADTV > 25cr requires turnover)
        all_syms = session.execute(text("""
            SELECT symbol FROM market_data_lake
            WHERE trade_date = :sd
            AND (close_raw * volume_raw) >= 10000000
            AND symbol NOT IN ('NIFTY50_INDEX', 'INDIA_VIX')
        """), {"sd": str(sd)}).scalars().all()

        qual_syms = []
        for sym in all_syms:
            res = screener.screen_single(sym, sd, apply_event_gates=False)
            if not res.passed:
                continue
            qual_syms.append(sym)

        # Check trend filter on qualified symbols
        if not qual_syms:
            pools[sd] = []
            continue

        cands = build_candidate_dicts(session, cfg, qual_syms, sd)
        trend_syms = []
        for c in cands:
            adj = c["adjusted_ohlcv"]
            if passes_trend_filter(adj["close_adj"], fast_sma, slow_sma):
                trend_syms.append(c["symbol"])

        pools[sd] = trend_syms
        if (idx + 1) % 25 == 0 or (idx + 1) == len(signal_dates):
            logger.info(f"Screened {idx + 1}/{len(signal_dates)} signal dates. (Pool size on {sd}: {len(trend_syms)})")

    # Cache to disk for instant future loads
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in pools.items()}, f)
    logger.info(f"Saved screened trend pools to {cache_path}.")

    return pools


def run_apples_to_apples_random_baseline(
    actual_trades: pd.DataFrame,
    cfg: dict,
    n_draws_target: int = 1000,
    seed: int = 42,
) -> pd.DataFrame:
    csv_path = OUTPUT_DIR / "apples_to_apples_random_trades.csv"
    if csv_path.exists():
        logger.info(f"Loading existing random baseline trades from {csv_path}...")
        df_rand = pd.read_csv(csv_path)
        df_rand["entry_date"] = pd.to_datetime(df_rand["entry_date"]).dt.date
        return df_rand

    random.seed(seed)
    np.random.seed(seed)

    rules = LifecycleRules.from_config(cfg)
    costs = CostModel.from_config(cfg)
    ex = cfg["execution"]
    slip_entry = float(ex["entry_slippage_pct"])
    slip_exit = float(ex["exit_slippage_pct"])
    gap_cap = float(ex["max_entry_gap_up_pct"])
    min_rr = float(ex["min_rr_at_fill"])
    atr_period = int(cfg["risk"]["atr_period"])
    atr_mult = float(cfg["risk"]["atr_stop_multiplier"])
    donchian_p = int(cfg["risk"]["donchian_period"])
    res_period = int(cfg["data"]["resistance_lookback_days"])

    with get_session() as s:
        # 1. Map each actual entry date to its prior trading session (signal date)
        unique_entry_dates = sorted(actual_trades["entry_date"].unique())
        
        # Get all market trading days around this period
        all_trading_days = s.execute(
            select(MarketDataLake.trade_date)
            .distinct()
            .where(MarketDataLake.trade_date >= date(2019, 10, 1), MarketDataLake.trade_date <= date(2026, 10, 16))
            .order_by(MarketDataLake.trade_date)
        ).scalars().all()
        t_days = [_to_date(d) for d in all_trading_days]
        t_day_set = set(t_days)

        entry_to_signal_date = {}
        for ed in unique_entry_dates:
            idx = t_days.index(ed) if ed in t_day_set else -1
            if idx > 0:
                entry_to_signal_date[ed] = t_days[idx - 1]

        unique_signal_dates = sorted(set(entry_to_signal_date.values()))
        pools = build_screened_trend_pools(cfg, unique_signal_dates, s)

        # 2. Simulate random entries matched to entry dates
        # Draw roughly (n_draws_target / len(actual_trades)) draws per actual trade
        draws_per_trade = max(5, int(round(n_draws_target / len(actual_trades))))
        logger.info(f"Targeting ~{draws_per_trade} draws per actual trade across {len(actual_trades)} trades...")

        random_results = []
        for trade_idx, actual_trade in actual_trades.iterrows():
            ed = actual_trade["entry_date"]
            sd = entry_to_signal_date.get(ed)
            if not sd or not pools.get(sd):
                continue

            available_syms = pools[sd]
            # Try random picks for this trade until we get successful fills or exhaust attempts
            successful_draws = 0
            attempts = 0
            while successful_draws < draws_per_trade and attempts < max(150, len(available_syms) * 2):
                attempts += 1
                sym = random.choice(available_syms)

                # Fetch candidate data on signal date sd
                c = build_candidate_dicts(s, cfg, [sym], sd)
                if not c:
                    continue
                adj = c[0]["adjusted_ohlcv"]
                if sd not in adj.index:
                    continue

                close_sd = float(adj.loc[sd]["close_adj"])
                atr_s = atr(adj["high_adj"], adj["low_adj"], adj["close_adj"], period=atr_period)
                atr_val = float(atr_s.loc[sd]) if sd in atr_s.index and pd.notna(atr_s.loc[sd]) else 0.0
                if atr_val <= 0:
                    continue

                stop_a = close_sd - atr_mult * atr_val
                stop_b = float(donchian_low(adj["low_adj"], period=donchian_p).loc[sd])
                live_stop = min(stop_a, stop_b)
                one_r = close_sd - live_stop
                if one_r <= 0:
                    continue

                target = float(donchian_high(adj["high_adj"], period=res_period).loc[sd])
                if (target - close_sd) / one_r < 1.5:
                    continue

                # Check T+1 execution bar on entry date ed
                ed_bar = s.execute(
                    select(MarketDataLake.open_raw, MarketDataLake.high_raw, MarketDataLake.low_raw, MarketDataLake.close_raw)
                    .where(MarketDataLake.symbol == sym, MarketDataLake.trade_date == ed)
                ).first()
                if not ed_bar:
                    continue

                open_ed = float(ed_bar[0])

                # Apply exact plan_entry_fill rules
                plan = plan_entry_fill(
                    ticket_entry=close_sd,
                    stop=live_stop,
                    target=target,
                    next_open=open_ed,
                    equity=1_000_000.0,
                    risk_pct=1.0,
                    slippage_pct=slip_entry,
                    max_gap_up_pct=gap_cap,
                    min_rr=min_rr,
                    cash=1_000_000.0,
                )
                if not plan.ok:
                    continue

                fill_price = plan.fill_price
                shares = plan.shares
                one_r_fill = fill_price - live_stop
                if one_r_fill <= 0 or shares <= 0:
                    continue

                # Forward simulation
                fwd_bars = s.execute(
                    select(MarketDataLake.trade_date, MarketDataLake.open_raw, MarketDataLake.high_raw,
                           MarketDataLake.low_raw, MarketDataLake.close_raw)
                    .where(MarketDataLake.symbol == sym, MarketDataLake.trade_date >= ed)
                    .order_by(MarketDataLake.trade_date)
                    .limit(45)
                ).all()

                if not fwd_bars:
                    continue

                # Forward returns from fill price at T+1, T+5, T+10, T+20 sessions after entry
                fwd_1 = (float(fwd_bars[1].close_raw) / fill_price - 1.0) * 100.0 if len(fwd_bars) > 1 else np.nan
                fwd_5 = (float(fwd_bars[5].close_raw) / fill_price - 1.0) * 100.0 if len(fwd_bars) > 5 else np.nan
                fwd_10 = (float(fwd_bars[10].close_raw) / fill_price - 1.0) * 100.0 if len(fwd_bars) > 10 else np.nan
                fwd_20 = (float(fwd_bars[20].close_raw) / fill_price - 1.0) * 100.0 if len(fwd_bars) > 20 else np.nan

                pos = PosState(
                    entry_price=fill_price,
                    initial_stop=live_stop,
                    live_stop=live_stop,
                    target=target,
                    highest_high=fill_price,
                    shares_remaining=shares,
                )

                closed = False
                exit_price = fill_price
                exit_reason = "OPEN"
                days_held = 0

                for b_idx, fb in enumerate(fwd_bars):
                    bar = Bar(float(fb.open_raw), float(fb.high_raw), float(fb.low_raw), float(fb.close_raw))
                    b_ctx = BarCtx(atr_val, False, True, None)
                    res = advance_one_bar(pos, bar, b_ctx, rules, slip_exit)
                    pos = res.pos
                    days_held = pos.days_held
                    if res.closed:
                        closed = True
                        exit_price = res.exits[-1].price if res.exits else bar.close
                        exit_reason = res.exits[-1].reason if res.exits else "STOP_HIT"
                        break

                if not closed:
                    exit_price = float(fwd_bars[-1].close_raw) * (1.0 - slip_exit / 100.0)

                buy_cost = costs.buy_cost(fill_price * shares)
                sell_cost = costs.sell_cost(exit_price * shares)
                gross_pnl = (exit_price - fill_price) * shares
                net_pnl = gross_pnl - (buy_cost + sell_cost)
                gross_r = gross_pnl / (shares * one_r_fill)
                net_r = net_pnl / (shares * one_r_fill)

                successful_draws += 1
                random_results.append({
                    "matched_trade_id": actual_trade["unique_trade_id"],
                    "symbol": sym,
                    "entry_date": ed,
                    "signal_date": sd,
                    "window": actual_trade["window"],
                    "fill_price": fill_price,
                    "gross_r": gross_r,
                    "net_r": net_r,
                    "ret_1": fwd_1,
                    "ret_5": fwd_5,
                    "ret_10": fwd_10,
                    "ret_20": fwd_20,
                    "exit_reason": exit_reason,
                    "days_held": days_held,
                })

    df_rand = pd.DataFrame(random_results)
    df_rand.to_csv(OUTPUT_DIR / "apples_to_apples_random_trades.csv", index=False)
    logger.info(f"Simulated {len(df_rand)} exact apples-to-apples random trades (saved to {OUTPUT_DIR / 'apples_to_apples_random_trades.csv'}).")
    return df_rand


def compute_trade_level_paired_statistics(actual_df: pd.DataFrame, rand_df: pd.DataFrame):
    """Compute exact trade-level pairing and date-clustered statistical tests."""
    logger.info("\n=== RE-ISSUED APPLES-TO-APPLES RANDOM BASELINE & PAIRED STATISTICS ===")

    # For each actual trade, get the mean forward returns and expectancy of its matched random draws
    grouped_rand = rand_df.groupby("matched_trade_id")
    rand_means = grouped_rand.agg({
        "ret_1": "mean",
        "ret_5": "mean",
        "ret_10": "mean",
        "ret_20": "mean",
        "gross_r": "mean",
        "net_r": "mean",
    }).rename(columns=lambda c: f"rand_{c}")

    merged = actual_df.merge(rand_means, left_on="unique_trade_id", right_index=True, how="inner")
    logger.info(f"Successfully paired {len(merged)} actual trades with matched random draws.")

    for win_tag in ["W1 (2020-21)", "W2 (2022-26)", "Pooled"]:
        sub = merged if win_tag == "Pooled" else merged[merged["window"] == win_tag]
        n_trades = len(sub)
        n_dates = sub["entry_date"].nunique()

        print(f"\n================================================================================")
        print(f"  {win_tag.upper()} (N = {n_trades} trades across {n_dates} unique entry dates)")
        print(f"================================================================================")

        rows = []
        for h, col in [(1, "ret_1"), (5, "ret_5"), (10, "ret_10"), (20, "ret_20")]:
            act_s = sub[col]
            rand_s = sub[f"rand_{col}"]
            diff_s = act_s - rand_s

            act_m = act_s.mean()
            rand_m = rand_s.mean()
            paired_diff = diff_s.mean()

            # Trade-level SE and t-stat
            se_trade = diff_s.std(ddof=1) / np.sqrt(len(diff_s.dropna()))
            t_trade = paired_diff / se_trade if se_trade > 0 else 0.0

            # Date-clustered standard error (resample dates with replacement, 2,000 iterations)
            dates = sub["entry_date"].unique()
            date_dict = {d: diff_s[sub["entry_date"] == d].values for d in dates}
            boot_diffs = np.zeros(2000)
            for bi in range(2000):
                sampled_d = np.random.choice(dates, size=len(dates), replace=True)
                boot_diffs[bi] = np.mean(np.concatenate([date_dict[d] for d in sampled_d]))
            se_clustered = np.std(boot_diffs)
            t_clustered = paired_diff / se_clustered if se_clustered > 0 else 0.0

            # Permutation test p-value (randomly flip sign of paired diffs)
            perm_means = np.zeros(5000)
            diff_arr = diff_s.dropna().values
            for pi in range(5000):
                signs = np.random.choice([-1.0, 1.0], size=len(diff_arr))
                perm_means[pi] = np.mean(diff_arr * signs)
            p_val = np.mean(np.abs(perm_means) >= np.abs(paired_diff))

            # Bonferroni alpha = 0.05 / 4 = 0.0125
            sig_status = "Significant" if p_val < 0.0125 else ("Suggestive" if p_val < 0.05 else "Not Sig")

            rows.append({
                "Horizon": f"T+{h}",
                "Actual Mean (SE)": f"{act_m:+.2f}% (±{act_s.std()/np.sqrt(n_trades):.2f}%)",
                "Random Mean (SE)": f"{rand_m:+.2f}% (±{rand_s.std()/np.sqrt(n_trades):.2f}%)",
                "Paired Diff": f"{paired_diff:+.2f}%",
                "Trade-level t": f"{t_trade:+.2f}",
                "Date-Clustered t": f"{t_clustered:+.2f}",
                "Perm p-value": f"{p_val:.4f}",
                "Status (alpha=0.0125)": sig_status,
            })

        print(pd.DataFrame(rows).to_string(index=False))

        # Expectancy comparison
        act_gross_r = sub["gross_r"].mean()
        act_net_r = sub["net_r"].mean()
        rand_gross_r = sub["rand_gross_r"].mean()
        rand_net_r = sub["rand_net_r"].mean()

        diff_net_r = sub["net_r"] - sub["rand_net_r"]
        m_diff_net = diff_net_r.mean()
        se_trade_net = diff_net_r.std() / np.sqrt(n_trades)
        t_net = m_diff_net / se_trade_net if se_trade_net > 0 else 0.0

        # Clustered bootstrap for Net Expectancy diff
        dates = sub["entry_date"].unique()
        date_dict_net = {d: diff_net_r[sub["entry_date"] == d].values for d in dates}
        boot_diff_net = np.zeros(2000)
        for bi in range(2000):
            sampled_d = np.random.choice(dates, size=len(dates), replace=True)
            boot_diff_net[bi] = np.mean(np.concatenate([date_dict_net[d] for d in sampled_d]))
        se_clust_net = np.std(boot_diff_net)
        t_clust_net = m_diff_net / se_clust_net if se_clust_net > 0 else 0.0
        p_one_sided_skill = np.mean(boot_diff_net <= 0.0)

        print(f"\nExpectancy Comparison:")
        print(f"  Actual:         Gross {act_gross_r:+.3f}R | Net {act_net_r:+.3f}R")
        print(f"  Matched Random: Gross {rand_gross_r:+.3f}R | Net {rand_net_r:+.3f}R")
        print(f"  Paired Net Diff: {m_diff_net:+.3f}R (Trade-level t = {t_net:+.2f}, Date-Clustered t = {t_clust_net:+.2f})")
        print(f"  Skill vs Drift (H0: Actual Net <= Random Net): One-sided p-value = {p_one_sided_skill:.4f}")


def main():
    cfg = load_config()
    with get_session() as s:
        df_w1, df_w2, df_all = load_actual_trades(s)
    rand_df = run_apples_to_apples_random_baseline(df_all, cfg, n_draws_target=1000, seed=42)
    compute_trade_level_paired_statistics(df_all, rand_df)


if __name__ == "__main__":
    main()
