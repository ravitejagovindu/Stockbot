"""COUNTS-ONLY study for the riskadj_momentum_daily rule. A study tool, NOT a strategy. Read-only on the lake; computes no return, P&L or forward price of any signal.

  py scripts/signal_count_riskadj_momentum_daily.py --out-dir DIR [--start 2016-01-01] [--end 2026-10-16] [--lake PATH] [--max-sessions N]

The rule is the strategy's own code (stockbot.strategies.riskadj_momentum_daily): the eligible set comes from the shared eligibility function, each name goes through ``assess`` and the ranking through
``order_signals``; EVERY session of the window is a signal session. Every session is evaluated through the as-of view at that date, so no bar after t can be read. Momentum and volatility are measurements
of the PAST at t. The re-entry cooldown needs the strategy's own exits, which exist only in an engine run, so it is NOT applied here (counts are for the rule without it; the cooldown can only remove names).
Reported per session: eligible, the funnel (short history, no bar, gap, bad price, ret <= 0, vol <= 0, ATR missing, qualifying), fewer than top_n qualifying, exact score ties (and one straddling the cut), the
sector spread of the top 25 (mapped vs UNMAPPED, distinct mapped sectors), the depth in the ranked list needed to find 12 names that pass the sector cap (greedy walk, position value = risk % / stop
distance, a name is admitted while its sector's exposure stays within ``max_sector_exposure_pct``; each UNMAPPED name is its own sector), the initial stop distance of the top 25 (share at the 8% floor,
median, p95) and the implied position size, the overlap of the top 25 with the previous session's, and how many of the top 12 are new against the previous session's top 12.
The lake is opened only through ``open_lake`` (mode=ro); the file is hashed before and after.
"""
import argparse
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
from stockbot.strategies.riskadj_momentum_daily.strategy import SPEC, assess, initial_stop, order_signals  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402

P = SPEC.params
REASONS = ("short", "stale", "gap", "bad_price", "ret_not_positive", "vol_not_positive", "atr_missing", "ok")
SLOTS = 12


def pct(a, q):
    return float(np.percentile(np.asarray(a, dtype=float), q)) if len(a) else None


def depth_for_slots(ranked, cfg, slots: int = SLOTS):
    """1-based position in ``ranked`` ([(symbol, stop_fraction)]) at which ``slots`` names have been admitted under the sector cap, else None. Position value (% of equity) = risk % / stop fraction;
    admitted while the sector's exposure stays <= max_sector_exposure_pct; each UNMAPPED name is its own sector. Cash and the total-risk cap are not applied."""
    risk = cfg.portfolio_risk.max_loss_pct_per_trade
    cap = cfg.portfolio_risk.max_sector_exposure_pct
    expo: dict = {}
    n = 0
    for i, (sym, frac) in enumerate(ranked, 1):
        sec, val = sector_for(sym), risk / frac
        if expo.get(sec, 0.0) + val <= cap + 1e-9:
            expo[sec] = expo.get(sec, 0.0) + val
            n += 1
            if n >= slots:
                return i
    return None


def score_session(view, cfg) -> dict:
    t = view.as_of
    n_long, top_n = int(P["ret_long"]), int(P["top_n"])
    cal = view.sessions(lookback=n_long + 1)
    win_start = cal[-n_long] if len(cal) >= n_long else None
    elig = list(eligible_symbols(view, cfg.universe))
    funnel = {k: 0 for k in REASONS}
    sigs, unusable_stop = [], 0
    for sym in elig:
        bars = view.adjusted_bars(sym, lookback=n_long + 1)
        reason, d = assess(bars, t, win_start, P) if win_start is not None else ("short", None)
        funnel[reason] += 1
        if reason != "ok":
            continue
        if initial_stop(d["close"], d["atr"], P)[0] <= 0.0:
            unusable_stop += 1
            continue
        sigs.append((sym, d["score"], d["close"], d["atr"], d["ret"], d["vol"]))
    ordered, _ = order_signals(view, sigs, top_n, int(P["tie_adtv_sessions"]))
    scores = [c[1] for c in sorted(sigs, key=lambda c: (-c[1], c[0]))]
    tie_names, tie_groups, straddle = 0, 0, False
    i = 0
    while i < len(scores):
        j = i
        while j + 1 < len(scores) and scores[j + 1] == scores[i]:
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
    risk = cfg.portfolio_risk.max_loss_pct_per_trade
    dist_pct, at_floor, size_pct = [], 0, []
    for sym, score, close, atr, ret, vol in top:
        _, dist = initial_stop(close, atr, P)
        dist_pct.append(100.0 * dist / close)
        at_floor += int(float(P["atr_mult"]) * atr <= float(P["stop_floor"]) * close)
        size_pct.append(risk / (dist / close))
    ranked = [(c[0], initial_stop(c[2], c[3], P)[1] / c[2]) for c in ordered]
    return {"date": t.isoformat(), "eligible": len(elig), "funnel": funnel, "qualifying": len(sigs), "unusable_stop": unusable_stop, "fewer_than_top_n": len(sigs) < top_n,
            "tie_groups": tie_groups, "tie_names": tie_names, "tie_straddles_cut": straddle, "top": [c[0] for c in top], "top_n_found": len(top), "mapped": len(mapped),
            "unmapped": len(sectors) - len(mapped), "distinct_mapped_sectors": len(cnt), "max_names_one_sector": max(cnt.values()) if cnt else 0,
            "depth_for_12_under_sector_cap": depth_for_slots(ranked, cfg), "stop_dist_pct": dist_pct, "at_floor": at_floor, "size_pct_of_equity": size_pct}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lake")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-sessions", type=int)
    args = ap.parse_args(argv)
    from stockbot.config.paths import lake_path
    lp = Path(args.lake) if args.lake else lake_path()
    before = fingerprint(lp, with_hash=True)
    cfg = load_shared_config()
    conn = open_lake(lp)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    sessions = [d for d in AsOfView(conn, end).sessions() if start <= d <= end]
    if args.max_sessions:
        sessions = sessions[:args.max_sessions]
    rows, t0 = [], time.time()
    for k, d in enumerate(sessions):
        rows.append(score_session(AsOfView(conn, d), cfg))
        if k % 50 == 0 or k == len(sessions) - 1:
            print(f"{k + 1}/{len(sessions)} {d} qualifying {rows[-1]['qualifying']} top {rows[-1]['top_n_found']} {time.time() - t0:.0f}s", flush=True)
    conn.close()
    after = fingerprint(lp, with_hash=True)
    prev25, prev12 = None, None
    for r in rows:
        cur25, cur12 = set(r["top"]), set(r["top"][:SLOTS])
        r["overlap_prev_top25"] = len(cur25 & prev25) if prev25 and cur25 else None
        r["new_in_top12"] = len(cur12 - prev12) if prev12 and len(cur12) == SLOTS else None
        prev25, prev12 = cur25, cur12
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summ = summarise(rows)
    summ.update(window=[start.isoformat(), end.isoformat()], asof_view=active_view_name(), spec_config_hash=SPEC.config_hash(), finsight_db={"before": before, "after": after, "unchanged": before == after},
                seconds=time.time() - t0, cooldown_applied=False)
    (out / "session_counts.json").write_text(json.dumps(rows), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: summ[k] for k in ("sessions", "fewer_than_top_n_sessions", "qualifying", "score_ties", "stop_distance_pct", "share_at_floor", "implied_position_pct_of_equity")}, indent=1, default=float))
    return 0 if before == after else 1


def summarise(rows) -> dict:
    full = [r for r in rows if r["top_n_found"] > 0]
    q = [r["qualifying"] for r in rows]
    allstops = [x for r in rows for x in r["stop_dist_pct"]]
    allsize = [x for r in rows for x in r["size_pct_of_equity"]]
    n_top = sum(r["top_n_found"] for r in rows)
    ov = [r["overlap_prev_top25"] for r in rows if r["overlap_prev_top25"] is not None]
    new12 = [r["new_in_top12"] for r in rows if r["new_in_top12"] is not None]
    depth = [r["depth_for_12_under_sector_cap"] for r in rows if r["depth_for_12_under_sector_cap"] is not None]
    funnel = {k: sum(r["funnel"][k] for r in rows) for k in REASONS}
    return {
        "sessions": len(rows), "first": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None, "sessions_with_a_top_list": len(full),
        "eligible": {"median": median(r["eligible"] for r in rows), "min": min(r["eligible"] for r in rows), "max": max(r["eligible"] for r in rows)} if rows else None,
        "funnel_total_name_sessions": funnel,
        "qualifying": {"median": median(q), "p5": pct(q, 5), "p95": pct(q, 95), "min": min(q), "max": max(q)} if rows else None,
        "fewer_than_top_n_sessions": sum(r["fewer_than_top_n"] for r in rows), "sessions_with_zero_qualifying": sum(1 for x in q if x == 0),
        "sessions_by_top_n_found": {str(k): sum(1 for r in rows if r["top_n_found"] == k) for k in sorted({r["top_n_found"] for r in rows})},
        "score_ties": {"sessions_with_any_tie": sum(1 for r in rows if r["tie_groups"]), "tie_groups": sum(r["tie_groups"] for r in rows), "names_in_ties": sum(r["tie_names"] for r in rows),
                       "qualifying_total": sum(q), "sessions_tie_straddles_the_cut": sum(1 for r in rows if r["tie_straddles_cut"])},
        "unusable_stop_name_sessions": sum(r["unusable_stop"] for r in rows),
        "top_names_total": n_top,
        "sector": {"mapped_share": sum(r["mapped"] for r in rows) / n_top if n_top else None, "unmapped_share": sum(r["unmapped"] for r in rows) / n_top if n_top else None,
                   "distinct_mapped_sectors": {"median": median(r["distinct_mapped_sectors"] for r in full), "min": min(r["distinct_mapped_sectors"] for r in full)} if full else None,
                   "max_names_one_sector": {"median": median(r["max_names_one_sector"] for r in full), "max": max(r["max_names_one_sector"] for r in full)} if full else None,
                   "depth_for_12_names_under_the_sector_cap": {"sessions_reached": len(depth), "sessions_not_reached": len(full) - len(depth), "median": median(depth) if depth else None,
                                                               "p95": pct(depth, 95), "max": max(depth) if depth else None,
                                                               "sessions_needing_more_than_25": sum(1 for x in depth if x > 25)}},
        "stop_distance_pct": {"median": pct(allstops, 50), "p5": pct(allstops, 5), "p95": pct(allstops, 95), "min": min(allstops) if allstops else None, "max": max(allstops) if allstops else None,
                              "mean": float(np.mean(allstops)) if allstops else None},
        "share_at_floor": sum(r["at_floor"] for r in rows) / n_top if n_top else None,
        "implied_position_pct_of_equity": {"median": pct(allsize, 50), "p5": pct(allsize, 5), "p95": pct(allsize, 95), "mean": float(np.mean(allsize)) if allsize else None},
        "day_to_day_overlap_top25": {"pairs": len(ov), "mean_names": float(np.mean(ov)) if ov else None, "median_names": median(ov) if ov else None,
                                     "share_of_top_n": float(np.mean(ov)) / int(P["top_n"]) if ov else None, "min": min(ov) if ov else None, "max": max(ov) if ov else None},
        "top12_changes": {"pairs": len(new12), "sessions_with_any_change": sum(1 for x in new12 if x > 0), "share_of_sessions_with_any_change": (sum(1 for x in new12 if x > 0) / len(new12)) if new12 else None,
                          "mean_new_names": float(np.mean(new12)) if new12 else None, "median_new_names": median(new12) if new12 else None, "max_new_names": max(new12) if new12 else None},
    }


if __name__ == "__main__":
    sys.exit(main())
