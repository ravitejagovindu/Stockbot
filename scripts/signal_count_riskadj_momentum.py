"""COUNTS-ONLY study for the riskadj_momentum rule (stage 1). A study tool, NOT a strategy. Read-only on the lake; computes no return, P&L or forward price of any signal.

  py scripts/signal_count_riskadj_momentum.py --out-dir DIR [--start 2016-01-01] [--end 2026-10-16] [--lake PATH] [--max-months N]

The rule is the strategy's own code (stockbot.strategies.riskadj_momentum): the eligible set comes from the shared eligibility function, each name goes through ``assess`` and the ranking
through ``order_signals``. Every signal session (first trading session of a calendar month) is evaluated through ``AsOfView(conn, t)``, so no bar after t can be read. Momentum here is the
12-1 return that the rule itself uses (a measurement of the PAST at t, not a forward return of a signal). Reported per signal month: eligible, the funnel (short history, no bar on t, gap, bad
price, ret <= 0, vol <= 0, ATR missing, qualifying), fewer than top_n qualifying, exact score ties (and a tie straddling the cut), sector spread of the top 25 (mapped sector vs UNMAPPED),
the initial stop distance of the top 25 (share at the 8% floor, median, p95) and the implied position size (risk 1% of equity / stop distance), the overlap with the previous month's top 25, and the
share of the top 25 that were also near_52w_high candidates on that session (that strategy's own code, top_n lifted so every candidate counts).
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
from stockbot.strategies.near_52w_high.strategy import SPEC as NEAR_SPEC, NearHighStrategy  # noqa: E402
from stockbot.strategies.riskadj_momentum.strategy import SPEC, assess, initial_stop, is_signal_session, order_signals  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402

P = SPEC.params
REASONS = ("short", "stale", "gap", "bad_price", "ret_not_positive", "vol_not_positive", "atr_missing", "ok")


def pct(a, q):
    return float(np.percentile(np.asarray(a, dtype=float), q)) if len(a) else None


def score_month(view, cfg, near_all) -> dict:
    t = view.as_of
    n_long, top_n = int(P["ret_long"]), int(P["top_n"])
    cal = view.sessions(lookback=n_long + 1)
    win_start = cal[-n_long] if len(cal) >= n_long else None           # first date of the last ret_long calendar sessions
    elig = list(eligible_symbols(view, cfg.universe))
    funnel = {k: 0 for k in REASONS}
    sigs, own_vs_cal_diff, unusable_stop = [], 0, 0
    for sym in elig:
        bars = view.adjusted_bars(sym, lookback=n_long + 1)
        reason, d = assess(bars, t, win_start, P) if win_start is not None else ("short", None)
        funnel[reason] += 1
        if reason != "ok":
            continue
        stop, dist = initial_stop(d["close"], d["atr"], P)
        if stop <= 0.0:
            unusable_stop += 1
            continue
        if len(cal) >= n_long + 1 and bars.index[-n_long - 1] != cal[0]:
            own_vs_cal_diff += 1                                          # the symbol's own bar t-252 is not the calendar's session t-252
        sigs.append((sym, d["score"], d["close"], d["atr"], d["ret"], d["vol"]))
    ordered, adtv_of = order_signals(view, sigs, top_n, int(P["tie_adtv_sessions"]))
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
    dist_pct, at_floor, size_pct = [], 0, []
    risk = cfg.portfolio_risk.max_loss_pct_per_trade
    for sym, score, close, atr, ret, vol in top:
        stop, dist = initial_stop(close, atr, P)
        frac = dist / close
        dist_pct.append(100.0 * frac)
        at_floor += int(float(P["atr_mult"]) * atr <= float(P["stop_floor"]) * close)
        size_pct.append(risk / frac)                                     # position value as % of equity = risk % / stop distance
    near_syms = near_all(view, elig, t)
    return {"date": t.isoformat(), "eligible": len(elig), "funnel": funnel, "qualifying": len(sigs), "unusable_stop": unusable_stop, "fewer_than_top_n": len(sigs) < top_n,
            "own_bar_differs_from_calendar": own_vs_cal_diff, "tie_groups": tie_groups, "tie_names": tie_names, "tie_straddles_cut": straddle, "top": [c[0] for c in top],
            "top_n_found": len(top), "mapped": len(mapped), "unmapped": len(sectors) - len(mapped), "distinct_mapped_sectors": len(cnt), "max_names_one_sector": max(cnt.values()) if cnt else 0,
            "names_sharing_a_mapped_sector": sum(v for v in cnt.values() if v > 1), "stop_dist_pct": dist_pct, "at_floor": at_floor, "size_pct_of_equity": size_pct,
            "near_high_candidates": len(near_syms), "top_also_near_high": sum(1 for c in top if c[0] in near_syms)}


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
    print(json.dumps({k: summ[k] for k in ("signal_months", "fewer_than_top_n_months", "qualifying", "score_ties", "stop_distance_pct", "share_at_floor", "implied_position_pct_of_equity")}, indent=1, default=float))
    return 0 if before == after else 1


def summarise(rows) -> dict:
    q = [r["qualifying"] for r in rows]
    allstops = [x for r in rows for x in r["stop_dist_pct"]]
    allsize = [x for r in rows for x in r["size_pct_of_equity"]]
    n_top = sum(r["top_n_found"] for r in rows)
    ov = [r["overlap_prev_top"] for r in rows if r["overlap_prev_top"] is not None]
    funnel = {k: sum(r["funnel"][k] for r in rows) for k in REASONS}
    return {
        "signal_months": len(rows), "first": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None,
        "eligible": {"median": median(r["eligible"] for r in rows), "min": min(r["eligible"] for r in rows), "max": max(r["eligible"] for r in rows)} if rows else None,
        "funnel_total_name_months": funnel,
        "qualifying": {"median": median(q), "p5": pct(q, 5), "p95": pct(q, 95), "min": min(q), "max": max(q)} if rows else None,
        "fewer_than_top_n_months": sum(r["fewer_than_top_n"] for r in rows), "months_with_zero_qualifying": sum(1 for x in q if x == 0),
        "months_by_top_n_found": {str(k): sum(1 for r in rows if r["top_n_found"] == k) for k in sorted({r["top_n_found"] for r in rows})},
        "score_ties": {"months_with_any_tie": sum(1 for r in rows if r["tie_groups"]), "tie_groups": sum(r["tie_groups"] for r in rows), "names_in_ties": sum(r["tie_names"] for r in rows),
                       "qualifying_total": sum(q), "months_tie_straddles_the_cut": sum(1 for r in rows if r["tie_straddles_cut"])},
        "own_bar_t_minus_252_differs_from_calendar": {"name_months": sum(r["own_bar_differs_from_calendar"] for r in rows), "of_qualifying": sum(q)},
        "unusable_stop_name_months": sum(r["unusable_stop"] for r in rows),
        "top_names_total": n_top, "sector": {"mapped_share": sum(r["mapped"] for r in rows) / n_top if n_top else None, "unmapped_share": sum(r["unmapped"] for r in rows) / n_top if n_top else None,
                                             "distinct_mapped_sectors_median": median(r["distinct_mapped_sectors"] for r in rows) if rows else None,
                                             "max_names_one_sector": {"median": median(r["max_names_one_sector"] for r in rows), "max": max(r["max_names_one_sector"] for r in rows)} if rows else None,
                                             "names_sharing_a_mapped_sector_share": sum(r["names_sharing_a_mapped_sector"] for r in rows) / n_top if n_top else None},
        "stop_distance_pct": {"median": pct(allstops, 50), "p5": pct(allstops, 5), "p95": pct(allstops, 95), "min": min(allstops) if allstops else None, "max": max(allstops) if allstops else None,
                              "mean": float(np.mean(allstops)) if allstops else None},
        "share_at_floor": sum(r["at_floor"] for r in rows) / n_top if n_top else None,
        "implied_position_pct_of_equity": {"median": pct(allsize, 50), "p5": pct(allsize, 5), "p95": pct(allsize, 95), "mean": float(np.mean(allsize)) if allsize else None},
        "overlap_with_previous_top": {"months": len(ov), "mean_names": float(np.mean(ov)) if ov else None, "median_names": median(ov) if ov else None, "share_of_top_n": float(np.mean(ov)) / int(P["top_n"]) if ov else None,
                                      "min": min(ov) if ov else None, "max": max(ov) if ov else None},
        "near_52w_high": {"top_also_near_high_share": sum(r["top_also_near_high"] for r in rows) / n_top if n_top else None,
                          "near_high_candidates_median": median(r["near_high_candidates"] for r in rows) if rows else None},
    }


if __name__ == "__main__":
    sys.exit(main())
