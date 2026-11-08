"""scripts/f9_trade_library.py — F9 step 1: a library of random-entry trades from the lake, simulated with the engine's own holding rules.

See docs/F9_PREREGISTRATION.md.  For every session t in 2020-01-01..2026-09-29 a random sample (<= 15) of names from that session's random-entry pool
(raw ADTV20 >= Rs25 cr, raw price >= Rs5, >= 252 sessions of history, not a fund, close > SMA50 > SMA200) gets one trade: signal at close t, fill at open t+1 plus
slippage, stop = min(entry - 2 ATR14, 30-session low), target = 252-session high (or entry + 3 ATR if already above it), lifecycle by
``engine_core.lifecycle_rules.advance_one_bar`` with LifecycleRules.from_config(strategy_config.yaml).  Sizing: 1% of Rs10,00,000 risked, no caps.
Each trade is stored as its daily P&L path as a fraction of equity (costs included).  Entries are skipped when Nifty <= its SMA200 or VIX > 22 (a simplified regime;
the kill-switch hysteresis is not replayed and the trailing multiplier is always the normal one).  Trades with an adjusted |daily move| > 40% in their path are dropped.
Read-only on the database.  Output: data/f9/trade_library.npz (+ a summary json).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import load_config                                                          # noqa: E402
from engine_core.adjustments import get_adjusted_series                                 # noqa: E402
from engine_core.costs import CostModel                                                 # noqa: E402
from engine_core.lifecycle_rules import Bar, BarCtx, LifecycleRules, PosState, advance_one_bar, parabolic_ref_close   # noqa: E402

OUT = ROOT / "data" / "f9"
START, END, AS_OF = date(2020, 1, 1), date(2026, 9, 29), date(2026, 9, 30)
EQUITY, RISK_PCT = 1_000_000.0, 1.0
PER_SESSION, SEED = 15, 20261108
MAX_HOLD = 250


def load(con) -> tuple[dict, pd.DataFrame, set]:
    funds = set(pd.read_csv(ROOT / "data/reference/fund_etf_symbols.csv")["symbol"].str.upper())
    q = ("select symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw from market_data_lake "
         "where trade_date >= '2018-06-01' and trade_date <= '2026-09-30' order by symbol, trade_date")
    df = pd.read_sql_query(q, con, parse_dates=["trade_date"])
    idx = df[df["symbol"].isin(["NIFTY50_INDEX", "INDIA_VIX"])]
    df = df[~df["symbol"].isin(["NIFTY50_INDEX", "INDIA_VIX"]) & ~df["symbol"].str.upper().isin(funds)]
    ca = pd.read_sql_query("select symbol, ex_date, action_type, ratio_numerator, ratio_denominator from corporate_actions_log "
                           "where action_type in ('SPLIT','BONUS')", con)
    cad: dict[str, list] = {}
    for r in ca.itertuples():
        cad.setdefault(r.symbol, []).append({"ex_date": date.fromisoformat(r.ex_date), "action_type": r.action_type,
                                             "ratio_numerator": r.ratio_numerator, "ratio_denominator": r.ratio_denominator})
    return {s: g for s, g in df.groupby("symbol")}, idx, cad


def atr_wilder(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    out = np.full(len(c), np.nan)
    if len(c) >= n:
        out[n - 1] = tr[:n].mean()
        for i in range(n, len(c)):
            out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def main() -> int:
    t0 = time.time()
    cfg = load_config()
    rules = LifecycleRules.from_config(cfg)
    costs = CostModel.from_config(cfg)
    slip_in, slip_out = cfg["execution"]["entry_slippage_pct"] / 100.0, cfg["execution"]["exit_slippage_pct"] / 100.0
    atr_mult = float(cfg["risk"]["atr_stop_multiplier"])
    don_n, res_n = int(cfg["risk"]["donchian_period"]), int(cfg["data"].get("resistance_lookback_days", 252))
    con = sqlite3.connect(f"file:{ROOT / 'finsight.db'}?mode=ro", uri=True, timeout=120)
    groups, idx, cad = load(con)
    nif = idx[idx["symbol"] == "NIFTY50_INDEX"].set_index("trade_date")["close_raw"]
    vix = idx[idx["symbol"] == "INDIA_VIX"].set_index("trade_date")["close_raw"]
    sessions = nif.index[(nif.index >= pd.Timestamp(START)) & (nif.index <= pd.Timestamp(END))]
    sess_pos = {d: i for i, d in enumerate(nif.index)}
    sma200n = nif.rolling(200).mean()
    regime_ok = {d: bool(nif[d] > sma200n[d] and vix.get(d, 14.0) <= 22.0) for d in sessions}

    # --- per-symbol arrays and pool membership ---------------------------------------------------------------
    sym_data, pool = {}, {}
    thr = float(cfg["universe"]["min_adtv_cr"]) * 1e7
    for sym, g in groups.items():
        if len(g) < 300:
            continue
        g = g.set_index(g["trade_date"].dt.date)
        raw = g[["open_raw", "high_raw", "low_raw", "close_raw", "volume_raw"]].astype(float)
        adj = get_adjusted_series(raw, cad.get(sym, []), as_of_date=AS_OF)
        o, h, l, c = (adj[k].values for k in ("open_adj", "high_adj", "low_adj", "close_adj"))
        cr, vol = raw["close_raw"].values, raw["volume_raw"].values
        adtv = pd.Series(cr * vol).rolling(20).mean().values
        s50, s200 = pd.Series(c).rolling(50).mean().values, pd.Series(c).rolling(200).mean().values
        atr = atr_wilder(h, l, c)
        dlow = pd.Series(l).rolling(don_n).min().values
        dhigh = pd.Series(h).rolling(res_n, min_periods=1).max().values
        dates = np.array([pd.Timestamp(x) for x in raw.index])
        ok = (adtv >= thr) & (cr >= 5.0) & (np.arange(len(c)) >= 252) & (c > s50) & (s50 > s200)
        sym_data[sym] = dict(dates=dates, o=o, h=h, l=l, c=c, atr=atr, dlow=dlow, dhigh=dhigh)
        dpos = {d: i for i, d in enumerate(dates)}
        sym_data[sym]["pos"] = dpos
        for i in np.flatnonzero(ok):
            d = dates[i]
            if d in regime_ok and regime_ok[d] and i + 1 < len(c) and dates[i + 1] > d:
                pool.setdefault(d, []).append(sym)
    print(f"loaded {len(sym_data)} symbols; pool sessions {len(pool)}; {time.time() - t0:.0f}s", flush=True)

    # --- simulate sampled trades -----------------------------------------------------------------------------
    rng = np.random.default_rng(SEED)
    sess_index = {d: i for i, d in enumerate(sessions)}
    recs, paths, dropped = [], [], {"artifact_move": 0, "bad_stop": 0, "no_fill_bar": 0}
    risk_inr = EQUITY * RISK_PCT / 100.0
    for d in sessions:
        names = pool.get(d, [])
        if not names:
            continue
        pick = rng.choice(len(names), size=min(PER_SESSION, len(names)), replace=False)
        for k in pick:
            sym = names[k]
            sd = sym_data[sym]
            i = sd["pos"][d]
            if i + 1 >= len(sd["c"]):
                dropped["no_fill_bar"] += 1
                continue
            entry = sd["o"][i + 1] * (1 + slip_in)
            a = sd["atr"][i]
            if not np.isfinite(a) or not np.isfinite(sd["dlow"][i]):
                dropped["bad_stop"] += 1
                continue
            stop = min(entry - atr_mult * a, sd["dlow"][i])
            if entry - stop <= 0:
                dropped["bad_stop"] += 1
                continue
            target = sd["dhigh"][i]
            if entry >= target:
                target = entry + 3.0 * a
            shares = int(risk_inr // (entry - stop))
            if shares < 1:
                dropped["bad_stop"] += 1
                continue
            pos = PosState(entry_price=entry, initial_stop=stop, live_stop=stop, target=target, highest_high=entry, shares_remaining=shares)
            eq_prev, pnl_real = 0.0, -costs.buy_cost(shares * entry)
            path, closed, artefact = [], False, False
            j = i + 1
            while j < len(sd["c"]) and j - (i + 1) < MAX_HOLD and not closed:
                if j > i + 1 and abs(sd["c"][j] / sd["c"][j - 1] - 1.0) > 0.40:
                    artefact = True
                    break
                bar = Bar(sd["o"][j], sd["h"][j], sd["l"][j], sd["c"][j])
                ref = parabolic_ref_close(list(sd["c"][max(0, j + 1 - rules.parabolic_lookback):j + 1]), rules.parabolic_lookback)
                bn = sess_pos.get(sd["dates"][j])
                bull = bool(bn is not None and nif.iloc[bn] > sma200n.iloc[bn]) if bn is not None else True
                res = advance_one_bar(pos, bar, BarCtx(float(sd["atr"][j]) if np.isfinite(sd["atr"][j]) else 0.0, False, bull, ref), rules, slip_out)
                pos = res.pos
                for e in res.exits:
                    pnl_real += (e.price - entry) * e.shares - costs.sell_cost(e.price * e.shares)
                closed = res.closed
                eq = pnl_real + pos.shares_remaining * (sd["c"][j] - entry)
                path.append((eq - eq_prev) / EQUITY)
                eq_prev = eq
                j += 1
            if artefact:
                dropped["artifact_move"] += 1
                continue
            if not closed:                                                      # still open at the data end or the hold cap: close at the last close
                last = sd["c"][j - 1]
                pnl_real += (last - entry) * pos.shares_remaining - costs.sell_cost(last * pos.shares_remaining)
                path[-1] += (-costs.sell_cost(last * pos.shares_remaining)) / EQUITY
            recs.append((sess_index.get(sd["dates"][i + 1], -1) if sd["dates"][i + 1] in sess_index else -1, len(path), sym))
            paths.append(np.array(path))
    keep = [k for k, r in enumerate(recs) if r[0] >= 0]
    recs = [recs[k] for k in keep]
    paths = [paths[k] for k in keep]
    lens = np.array([r[1] for r in recs]); starts = np.array([r[0] for r in recs])
    flat = np.concatenate(paths); offs = np.r_[0, np.cumsum(lens)]
    tot = np.array([p.sum() for p in paths])
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / "trade_library.npz", start=starts, length=lens, offset=offs, flat=flat,
                        symbol=np.array([r[2] for r in recs]), session_dates=np.array([d.strftime("%Y-%m-%d") for d in sessions]))
    summ = dict(trades=len(recs), sessions=len(sessions), sessions_with_pool=len(pool), dropped=dropped, mean_hold_sessions=float(lens.mean()),
                mean_trade_return_pct_of_equity=float(tot.mean() * 100), mean_R_net=float(tot.mean() / (RISK_PCT / 100.0)),
                median_R_net=float(np.median(tot) / (RISK_PCT / 100.0)), sd_R_net=float(tot.std() / (RISK_PCT / 100.0)),
                share_winners=float((tot > 0).mean()), seconds=round(time.time() - t0))
    (OUT / "trade_library_summary.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps(summ, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
