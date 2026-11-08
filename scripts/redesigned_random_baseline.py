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

from stockbot.config.legacy_loader import load_config
from data.db.connection import get_session
from data.db.models import MarketDataLake
from engine_core.candidate_builder import build_candidate_dicts
from stockbot.risk.costs import CostModel
from engine_core.entry_filters import passes_trend_filter
from stockbot.data.indicators import atr, donchian_high, donchian_low
from engine_core.lifecycle_rules import (
    Bar,
    BarCtx,
    LifecycleRules,
    PosState,
    advance_one_bar,
    parabolic_ref_close,
    plan_entry_fill,
)
from engine_core.regime_filter import RegimeFilter
from engine_core.regime_gates import is_bull
from stockbot.validation.trade_metrics import add_r_columns, compute_trade_r
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


def trimmed_mean(arr, proportion_to_cut: float = 0.05) -> float:
    """Compute trimmed mean cutting proportion_to_cut from each tail."""
    clean = np.asarray(arr)[~np.isnan(arr)]
    if len(clean) == 0:
        return float("nan")
    vals = np.sort(clean)
    n = len(vals)
    k = int(n * proportion_to_cut)
    if k > 0 and 2 * k < n:
        return float(np.mean(vals[k:-k]))
    return float(np.mean(vals))


def load_actual_trades(session) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    w1_path = OUTPUT_DIR / "trades_pass1_window_2020_2021.csv"
    w2_path = OUTPUT_DIR / "trades_pass1_window_2022_2026.csv"
    df_w1 = pd.read_csv(w1_path)
    df_w2 = pd.read_csv(w2_path)
    df_w1["window"] = "W1 (2020-21)"
    df_w2["window"] = "W2 (2022-26)"
    df_all = pd.concat([df_w1, df_w2], ignore_index=True)
    # R columns come from the single definition in stockbot.validation.trade_metrics (F1).
    df_w1, df_w2, df_all = (add_r_columns(d) for d in (df_w1, df_w2, df_all))
    for df in [df_w1, df_w2, df_all]:
        df["entry_date"] = pd.to_datetime(df["entry_date"]).dt.date
        df["exit_date"] = pd.to_datetime(df["exit_date"]).dt.date
        df["one_r"] = df["entry_price"] - df["stop"]
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


def tune_windows(cfg: dict) -> list[tuple[str, date, date]]:
    """Backtest windows come from strategy_config.yaml (TUNE role only — the TEST window is never touched here)."""
    out = []
    for r in cfg.get("backtest", {}).get("regimes", []):
        if r.get("role", "TUNE") == "TUNE":
            out.append((r["name"], date.fromisoformat(str(r["start"])), date.fromisoformat(str(r["end"]))))
    return out


def run_apples_to_apples_random_baseline(
    actual_trades: pd.DataFrame,
    cfg: dict,
    n_draws_target: int = 1000,
    seed: int = 42,
    force_rerun: bool = False,
    output_filename: str = "apples_to_apples_random_trades.csv",
) -> pd.DataFrame:
    """Matched random baseline (F6): same signal-date universe, same sizer, same adjusted price path, same fill/exit
    rules and the same R function as the Simulator (see backtest/path_sim.py). Dates come from the config windows."""
    from backtest.path_sim import simulate_position_path
    from backtest.simulator import Simulator
    from engine_core.risk_sizing import RiskAndSizingEngine

    csv_path = OUTPUT_DIR / output_filename
    if csv_path.exists() and not force_rerun:
        logger.info(f"Loading existing random baseline trades from {csv_path}...")
        df_rand = pd.read_csv(csv_path)
        df_rand["entry_date"] = pd.to_datetime(df_rand["entry_date"]).dt.date
        return df_rand

    random.seed(seed)
    np.random.seed(seed)

    rules = LifecycleRules.from_config(cfg)
    costs = CostModel.from_config(cfg)
    sizer = RiskAndSizingEngine(cfg)
    windows = tune_windows(cfg)
    if not windows:
        raise RuntimeError("No TUNE windows in strategy_config.yaml backtest.regimes")
    first_start = min(w[1] for w in windows)
    last_end = max(w[2] for w in windows)

    with get_session() as s:
        # 1. Map each actual entry date to its prior trading session (signal date)
        unique_entry_dates = sorted(actual_trades["entry_date"].unique())
        all_trading_days = s.execute(
            select(MarketDataLake.trade_date)
            .distinct()
            .where(MarketDataLake.trade_date >= first_start - timedelta(days=120), MarketDataLake.trade_date <= last_end)
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

        # Regime per window: in-memory, seeded exactly like Simulator.run (no database writes)
        logger.info("Pre-computing macro regime state for every window session (in memory)...")
        helper = Simulator.__new__(Simulator)
        helper.cfg, helper.s = cfg, s
        daily_regime = {}
        for wname, w_start, w_end in windows:
            seed_state = helper._derive_regime_seed(w_start, None)
            regime = RegimeFilter(cfg, s, persist=False,
                                  seed_state={k: seed_state[k] for k in ("kill_switch_active", "reentry_consecutive_count")})
            for d in [x for x in t_days if w_start <= x <= w_end]:
                rs = regime.evaluate(d)
                ks = bool(rs.kill_switch_active)
                daily_regime[d] = (ks, is_bull(ks, rs.nifty_close, rs.nifty_sma200))
        logger.info(f"Pre-computed macro regime for {len(daily_regime)} sessions.")

        def window_end_for(ed: date) -> date:
            for _, w_start, w_end in windows:
                if w_start <= ed <= w_end:
                    return w_end
            return last_end

        draws_per_trade = max(5, int(round(n_draws_target / len(actual_trades))))
        logger.info(f"Targeting ~{draws_per_trade} draws per actual trade across {len(actual_trades)} trades...")

        random_results = []
        for trade_idx, actual_trade in actual_trades.iterrows():
            ed = actual_trade["entry_date"]
            sd = entry_to_signal_date.get(ed)
            if not sd or not pools.get(sd):
                continue
            available_syms = pools[sd]
            successful_draws, attempts = 0, 0
            while successful_draws < draws_per_trade and attempts < max(150, len(available_syms) * 2):
                attempts += 1
                sym = random.choice(available_syms)
                cand = build_candidate_dicts(s, cfg, [sym], sd)
                if not cand or sd not in cand[0]["adjusted_ohlcv"].index:
                    continue
                # identical sizing / R:R gating as the real pipeline (no portfolio, 1M equity)
                setup = sizer.compute_setup(
                    symbol=sym, eval_date=sd, adjusted_ohlcv=cand[0]["adjusted_ohlcv"],
                    raw_ohlcv=cand[0]["raw_ohlcv"], account_equity=1_000_000.0, current_positions=[],
                    sector=cand[0]["sector"])
                if setup.blocked:
                    continue
                res = simulate_position_path(s, cfg, sym, setup, ed, window_end_for(ed), daily_regime,
                                             equity=1_000_000.0, cash=1_000_000.0, rules=rules, costs=costs)
                if not res["ok"] or res.get("excluded_ca"):
                    continue
                successful_draws += 1
                random_results.append({
                    "matched_trade_id": actual_trade["unique_trade_id"],
                    "symbol": sym,
                    "entry_date": ed,
                    "signal_date": sd,
                    "window": actual_trade["window"],
                    "fill_price": res["fill_price"],
                    "risk_inr": res["risk_inr"],
                    "gross_r": res["gross_r"],
                    "net_r": res["net_r"],
                    "net_r_after_tax": res["net_r_after_tax"],
                    "pnl_gross": res["pnl_gross"],
                    "costs": res["costs"],
                    "pnl_net": res["pnl_net"],
                    "exit_reason": res["exit_reason"],
                    "days_held": res["days_held"],
                    # Diagnostic forward returns were computed from RAW closes (wrong across splits) and are not used
                    # by any gate; kept as NaN so the paired-statistics printout still runs (F6).
                    "ret_1": np.nan, "ret_5": np.nan, "ret_10": np.nan, "ret_20": np.nan,
                })

    df_rand = pd.DataFrame(random_results)
    df_rand.to_csv(csv_path, index=False)
    logger.info(f"Simulated {len(df_rand)} exact apples-to-apples random trades (saved to {csv_path}).")
    return df_rand


def generate_matched_random_baseline(
    actual_trades: pd.DataFrame,
    cfg: dict,
    config_id: str,
    n_draws_per_trade: int = 5,
    seed: int = 42,
    force_rerun: bool = False,
) -> pd.DataFrame:
    """Generate or load matched random baseline for an arbitrary configuration's trades."""
    target_draws = max(500, len(actual_trades) * n_draws_per_trade)
    out_name = f"apples_to_apples_random_trades_{config_id}.csv" if config_id != "CFG-00" else "apples_to_apples_random_trades.csv"
    return run_apples_to_apples_random_baseline(
        actual_trades=actual_trades,
        cfg=cfg,
        n_draws_target=target_draws,
        seed=seed,
        force_rerun=force_rerun,
        output_filename=out_name,
    )


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
        "days_held": "mean",
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

        act_net_med = sub["net_r"].median()
        rand_net_med = sub["rand_net_r"].median()
        act_net_trim = trimmed_mean(sub["net_r"].values, 0.05)
        rand_net_trim = trimmed_mean(sub["rand_net_r"].values, 0.05)

        diff_net_r = sub["net_r"] - sub["rand_net_r"]
        m_diff_net = diff_net_r.mean()
        med_diff_net = diff_net_r.median()
        trim_diff_net = trimmed_mean(diff_net_r.values, 0.05)

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

        # Raw draw-level metrics (Basis B: unaggregated draws)
        sub_raw = rand_df if win_tag == "Pooled" else rand_df[rand_df["window"] == win_tag]
        raw_gross_r = sub_raw["gross_r"].mean()
        raw_net_r = sub_raw["net_r"].mean()
        raw_net_med = sub_raw["net_r"].median()
        raw_net_trim = trimmed_mean(sub_raw["net_r"].values, 0.05)
        raw_days = sub_raw["days_held"]
        raw_days_gt85 = int((raw_days > 85).sum())
        raw_r_gt85 = float(sub_raw[raw_days > 85]["net_r"].mean()) if raw_days_gt85 > 0 else float("nan")

        # Holding duration statistics
        act_days = sub["days_held"]
        rand_days = sub["rand_days_held"]

        print(f"\nExpectancy Comparison:")
        print(f"  Actual Trades (N={n_trades}):")
        print(f"    Gross Mean {act_gross_r:+.3f}R | Net Mean {act_net_r:+.3f}R | Net Median {act_net_med:+.3f}R | Net 5% Trimmed {act_net_trim:+.3f}R")
        print(f"  Basis A: Trade-Level Averaged Random (N={n_trades} trade-averaged pairs):")
        print(f"    Gross Mean {rand_gross_r:+.3f}R | Net Mean {rand_net_r:+.3f}R | Net Median {rand_net_med:+.3f}R | Net 5% Trimmed {rand_net_trim:+.3f}R")
        print(f"    Paired Diff: Mean {m_diff_net:+.3f}R | Median {med_diff_net:+.3f}R | 5% Trimmed {trim_diff_net:+.3f}R")
        print(f"    Trade t = {t_net:+.2f} | Clustered t = {t_clust_net:+.2f} | Skill vs Drift p = {p_one_sided_skill:.4f}")
        print(f"  Basis B: Raw Draw-Level Random (N={len(sub_raw)} individual draws):")
        print(f"    Gross Mean {raw_gross_r:+.3f}R | Net Mean {raw_net_r:+.3f}R | Net Median {raw_net_med:+.3f}R | Net 5% Trimmed {raw_net_trim:+.3f}R")

        print(f"\nHolding Duration Statistics:")
        print(f"  Actual Trades:                   Mean {act_days.mean():.1f} d | Median {act_days.median():.0f} d | Max {act_days.max():.0f} d | Held > 85d: {(act_days > 85).sum()}/{n_trades}")
        print(f"  Basis A (Trade-Averaged Random): Mean {rand_days.mean():.1f} d | Median {rand_days.median():.0f} d | Max {rand_days.max():.1f} d | Held > 85d: {(rand_days > 85).sum()}/{n_trades}")
        print(f"  Basis B (Raw Draws Random):      Mean {raw_days.mean():.1f} d | Median {raw_days.median():.0f} d | Max {raw_days.max():.0f} d | Held > 85d: {raw_days_gt85}/{len(sub_raw)} (Avg R: {raw_r_gt85:+.2f}R)")


def main():
    cfg = load_config()
    with get_session() as s:
        df_w1, df_w2, df_all = load_actual_trades(s)
    rand_df = run_apples_to_apples_random_baseline(df_all, cfg, n_draws_target=1000, seed=42, force_rerun=False)
    compute_trade_level_paired_statistics(df_all, rand_df)


if __name__ == "__main__":
    main()
