"""COUNTS-ONLY study for the lowvol_uptrend rule. A study tool, NOT a strategy. Read-only on the lake; computes no return, P&L or forward price of any signal.

  py scripts/signal_count_lowvol_uptrend.py --out-dir DIR [--start 2016-01-01] [--end 2026-10-16] [--lake PATH] [--max-months N]

The rule is the strategy's own code (stockbot.strategies.lowvol_uptrend): the eligible set comes from the shared eligibility function, each name goes through ``assess`` and the ranking through
``order_signals``. Every signal session (first trading session of a calendar month) is evaluated through the as-of view at that date, so no bar after t can be read. The volatility is a
measurement of the PAST at t. Reported per signal month: eligible, the funnel (short history, no bar on t, gap, bad price, SMA window gap, below SMA200, vol <= 0, ATR missing, qualifying), fewer
than top_n qualifying, exact vol ties (and a tie straddling the cut), sector spread of the top 25 (mapped sector vs UNMAPPED, distinct mapped sectors, how far down the full ranked list one must go to
find 8 names in different sectors, each UNMAPPED name counting as its own), the initial stop distance of the top 25 (share at the 8% floor, median, p95) and the implied position size (risk % of
equity / stop distance), the overlap with the previous month's top 25, the share of the top 25 that were riskadj_momentum top-25 names the same month and near_52w_high candidates that day (those
strategies' own code, near_52w_high with top_n lifted so every candidate counts), and whether the Nifty close was below its own 200-session SMA.
The lake is opened only through ``open_lake`` (mode=ro); the file is hashed before and after.
"""
import argparse
import dataclasses
import json
import sys
import time
from datetime import date
from pathlib import Path
from statistics import median

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import AsOfView, active_view_name  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.data.sector_map import UNMAPPED_PREFIX, sector_for  # noqa: E402
from stockbot.data_checks.near_high_signal_count import fingerprint  # noqa: E402
from stockbot.strategies.lowvol_uptrend.strategy import SPEC, assess, initial_stop, is_signal_session, order_signals  # noqa: E402
from stockbot.strategies.near_52w_high.strategy import SPEC as NEAR_SPEC, NearHighStrategy  # noqa: E402
from stockbot.strategies.riskadj_momentum import strategy as RA  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402

P = SPEC.params
REASONS = ("short", "stale", "gap", "bad_price", "sma_gap", "below_sma", "vol_not_positive", "atr_missing", "ok")
DISTINCT_TARGET = 8
NIFTY = "NIFTY50_INDEX"


def pct(a, q):
    return float(np.percentile(np.asarray(a, dtype=float), q)) if len(a) else None


def depth_for_distinct(symbols, target: int):
    """1-based position in the ranked list at which ``target`` distinct sectors (each UNMAPPED name its own) have been seen; None if the list never gets there."""
    seen: set = set()
    for i, s in enumerate(symbols, 1):
        seen.add(sector_for(s))
        if len(seen) >= target:
            return i
    return None


def riskadj_top(view, elig, t) -> set:
    p = RA.SPEC.params
    n_long, top_n = int(p["ret_long"]), int(p["top_n"])
    cal = view.sessions(lookback=n_long + 1)
    if len(cal) < n_long:
        return set()
    win_start = cal[-n_long]
    sigs = []
    for sym in elig:
        reason, d = RA.assess(view.adjusted_bars(sym, lookback=n_long + 1), t, win_start, p)
        if reason == "ok" and RA.initial_stop(d["close"], d["atr"], p)[0] > 0.0:
            sigs.append((sym, d["score"]))
    ordered, _ = RA.order_signals(view, sigs, top_n, int(p["tie_adtv_sessions"]))
    return {c[0] for c in ordered[:top_n]}


def nifty_below_sma(view, n: int = 200):
    b = view.raw_bars(NIFTY, lookback=n)["close_raw"]
    if len(b) < n:
        return None
    return bool(float(b.iloc[-1]) < float(b.mean()))


def score_month(view, cfg, near_all) -> dict:
    t = view.as_of
    n, top_n = int(P["vol_window"]), int(P["top_n"])
    cal = view.sessions(lookback=n)
    ok_cal = len(cal) >= n
    win_start, sma_start = (cal[0], cal[-int(P["sma_window"])]) if ok_cal else (None, None)
    elig = list(eligible_symbols(view, cfg.universe))
    funnel = {k: 0 for k in REASONS}
    sigs, unusable_stop = [], 0
    for sym in elig:
        reason, d = assess(view.adjusted_bars(sym, lookback=n + 1), t, win_start, sma_start, P) if ok_cal else ("short", None)
        funnel[reason] += 1
        if reason != "ok":
            continue
        if initial_stop(d["close"], d["atr"], P)[0] <= 0.0:
            unusable_stop += 1
            continue
        sigs.append((sym, d["vol"], d["close"], d["atr"], d["sma"]))
    ordered, adtv_of = order_signals(view, sigs, top_n, int(P["tie_adtv_sessions"]))
    vols = [c[1] for c in sorted(sigs, key=lambda c: (c[1], c[0]))]
    tie_names, tie_groups, straddle = 0, 0, False
    i = 0
    while i < len(vols):
        j = i
        while j + 1 < len(vols) and vols[j + 1] == vols[i]:
            j += 1
        if j > i:
            tie_groups += 1
            tie_names += j - i + 1
            straddle = straddle or (i < top_n <= j)
        i = j + 1
    top = ordered[:top_n]
    sectors = [sector_for(c[0]) for c in top]
    mapped = [s for s in sectors if not s.startswith(UNMAPPED_PREFIX)]
    cnt: dict = {}
    for s in mapped:
        cnt[s] = cnt.get(s, 0) + 1
    dist_pct, at_floor, size_pct = [], 0, []
    risk = cfg.portfolio_risk.max_loss_pct_per_trade
    for sym, vol, close, atr, sma in top:
        _, dist = initial_stop(close, atr, P)
        dist_pct.append(100.0 * dist / close)
        at_floor += int(float(P["atr_mult"]) * atr <= float(P["stop_floor"]) * close)
        size_pct.append(risk / (dist / close))
    near_syms = near_all(view, elig, t)
    ra = riskadj_top(view, elig, t)
    return {"date": t.isoformat(), "eligible": len(elig), "funnel": funnel, "qualifying": len(sigs), "unusable_stop": unusable_stop, "fewer_than_top_n": len(sigs) < top_n,
            "tie_groups": tie_groups, "tie_names": tie_names, "tie_straddles_cut": straddle, "top": [c[0] for c in top], "top_n_found": len(top), "mapped": len(mapped),
            "unmapped": len(sectors) - len(mapped), "distinct_mapped_sectors": len(cnt), "max_names_one_sector": max(cnt.values()) if cnt else 0,
            "depth_for_8_distinct": depth_for_distinct([c[0] for c in ordered], DISTINCT_TARGET), "stop_dist_pct": dist_pct, "at_floor": at_floor, "size_pct_of_equity": size_pct,
            "near_high_candidates": len(near_syms), "top_also_near_high": sum(1 for c in top if c[0] in near_syms), "riskadj_top_n": len(ra), "top_also_riskadj": sum(1 for c in top if c[0] in ra),
            "nifty_below_sma200": nifty_below_sma(view)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lake")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-months", type=int)
    args = ap.parse_args(argv)
    from stockbot.config.paths import lake_path
    lp = Path(args.lake) if args.lake else lake_path()
    before = fingerprint(lp, with_hash=True)
    cfg = load_shared_config()
    conn = open_lake(lp)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    sessions = [d for d in AsOfView(conn, end).sessions()]
    months = [d for d in sessions if start <= d <= end and is_signal_session(AsOfView(conn, d))]
    if args.max_months:
        months = months[:args.max_months]
    near_strat = NearHighStrategy(dataclasses.replace(NEAR_SPEC, params={**NEAR_SPEC.params, "top_n": 100000}))

    def near_all(view, elig, t):
        return {p.symbol for p in near_strat.propose(view, elig, t, {}, {})[0]}

    rows, t0 = [], time.time()
    for k, d in enumerate(months):
        rows.append(score_month(AsOfView(conn, d), cfg, near_all))
        print(f"{k + 1}/{len(months)} {d} qualifying {rows[-1]['qualifying']} top {rows[-1]['top_n_found']} {time.time() - t0:.0f}s", flush=True)
    conn.close()
    after = fingerprint(lp, with_hash=True)
    prev: set = set()
    for r in rows:
        cur = set(r["top"])
        r["overlap_prev_top"] = len(cur & prev) if prev else None
        prev = cur
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summ = summarise(rows)
    summ.update(window=[start.isoformat(), end.isoformat()], asof_view=active_view_name(), spec_config_hash=SPEC.config_hash(), finsight_db={"before": before, "after": after, "unchanged": before == after},
                seconds=time.time() - t0)
    (out / "monthly_counts.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: summ[k] for k in ("signal_months", "fewer_than_top_n_months", "qualifying", "vol_ties", "stop_distance_pct", "share_at_floor", "implied_position_pct_of_equity")}, indent=1, default=float))
    return 0 if before == after else 1


def summarise(rows) -> dict:
    q = [r["qualifying"] for r in rows]
    allstops = [x for r in rows for x in r["stop_dist_pct"]]
    allsize = [x for r in rows for x in r["size_pct_of_equity"]]
    n_top = sum(r["top_n_found"] for r in rows)
    ov = [r["overlap_prev_top"] for r in rows if r["overlap_prev_top"] is not None]
    funnel = {k: sum(r["funnel"][k] for r in rows) for k in REASONS}
    depth = [r["depth_for_8_distinct"] for r in rows if r["depth_for_8_distinct"] is not None]
    nb = [r["nifty_below_sma200"] for r in rows if r["nifty_below_sma200"] is not None]
    n_ra = sum(r["riskadj_top_n"] for r in rows)
    return {
        "signal_months": len(rows), "first": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None,
        "eligible": {"median": median(r["eligible"] for r in rows), "min": min(r["eligible"] for r in rows), "max": max(r["eligible"] for r in rows)} if rows else None,
        "funnel_total_name_months": funnel,
        "funnel_median_per_month": {k: median(r["funnel"][k] for r in rows) for k in REASONS} if rows else None,
        "qualifying": {"median": median(q), "p5": pct(q, 5), "p95": pct(q, 95), "min": min(q), "max": max(q)} if rows else None,
        "fewer_than_top_n_months": sum(r["fewer_than_top_n"] for r in rows), "months_with_zero_qualifying": sum(1 for x in q if x == 0),
        "months_by_top_n_found": {str(k): sum(1 for r in rows if r["top_n_found"] == k) for k in sorted({r["top_n_found"] for r in rows})},
        "vol_ties": {"months_with_any_tie": sum(1 for r in rows if r["tie_groups"]), "tie_groups": sum(r["tie_groups"] for r in rows), "names_in_ties": sum(r["tie_names"] for r in rows),
                     "qualifying_total": sum(q), "months_tie_straddles_the_cut": sum(1 for r in rows if r["tie_straddles_cut"])},
        "unusable_stop_name_months": sum(r["unusable_stop"] for r in rows),
        "top_names_total": n_top, "sector": {"mapped_share": sum(r["mapped"] for r in rows) / n_top if n_top else None, "unmapped_share": sum(r["unmapped"] for r in rows) / n_top if n_top else None,
                                             "distinct_mapped_sectors": {"median": median(r["distinct_mapped_sectors"] for r in rows), "min": min(r["distinct_mapped_sectors"] for r in rows)} if rows else None,
                                             "max_names_one_sector": {"median": median(r["max_names_one_sector"] for r in rows), "max": max(r["max_names_one_sector"] for r in rows)} if rows else None,
                                             "depth_for_8_distinct_sectors_in_ranked_list": {"months_reached": len(depth), "months_not_reached": len(rows) - len(depth), "median": median(depth) if depth else None,
                                                                                            "p95": pct(depth, 95), "max": max(depth) if depth else None}},
        "stop_distance_pct": {"median": pct(allstops, 50), "p5": pct(allstops, 5), "p95": pct(allstops, 95), "min": min(allstops) if allstops else None, "max": max(allstops) if allstops else None,
                              "mean": float(np.mean(allstops)) if allstops else None},
        "share_at_floor": sum(r["at_floor"] for r in rows) / n_top if n_top else None,
        "implied_position_pct_of_equity": {"median": pct(allsize, 50), "p5": pct(allsize, 5), "p95": pct(allsize, 95), "mean": float(np.mean(allsize)) if allsize else None},
        "overlap_with_previous_top": {"months": len(ov), "mean_names": float(np.mean(ov)) if ov else None, "median_names": median(ov) if ov else None,
                                      "share_of_top_n": float(np.mean(ov)) / int(P["top_n"]) if ov else None, "min": min(ov) if ov else None, "max": max(ov) if ov else None},
        "riskadj_momentum": {"top_also_riskadj_top_share": sum(r["top_also_riskadj"] for r in rows) / n_top if n_top else None, "riskadj_top_names_total": n_ra},
        "near_52w_high": {"top_also_near_high_share": sum(r["top_also_near_high"] for r in rows) / n_top if n_top else None,
                          "near_high_candidates_median": median(r["near_high_candidates"] for r in rows) if rows else None},
        "nifty_below_own_sma200": {"months_with_value": len(nb), "months_below": sum(nb), "share": sum(nb) / len(nb) if nb else None},
    }


if __name__ == "__main__":
    sys.exit(main())
