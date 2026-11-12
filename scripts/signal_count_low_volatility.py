"""Counts-only signal study for the low_volatility rule (stage 1). Read-only on the lake; no return, P&L or forward price is computed. Run: py scripts/signal_count_low_volatility.py --help

Evaluates the strategy's own ``score`` on the first session of every calendar month (so the strategy and the study are one implementation), with the shared eligibility rule and
the shared caps. Occupancy model: signal at the close of session j, entry at the open of j+1 (session 1), market exit requested at the close of session 21 and executed at
the open of session 22 (``fixed_hold_21``), a symbol already held is skipped, a slot is free only if the exit executed before the signal close. Position size = risk % / stop
distance (1 / 10 = 10% of equity) and the shared sector cap (15%, unmapped symbols share UNKNOWN) as in the engine. Ignores stops, the risk cap, costs, gap rules, cash and
missing bars.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.config.paths import lake_path  # noqa: E402
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import AsOfView  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.data.sector_map import sector_for  # noqa: E402
from stockbot.strategies.low_volatility import SPEC, LowVolatilityStrategy  # noqa: E402
from stockbot.strategies.low_volatility.strategy import is_signal_session  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402

HOLD = 21


def fingerprint(path, with_hash=True) -> dict:
    p = Path(path)
    st = p.stat()
    h = None
    if with_hash:
        d = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                d.update(chunk)
        h = d.hexdigest()
    return dict(size=st.st_size, mtime_ns=st.st_mtime_ns, mtime_iso=datetime.fromtimestamp(st.st_mtime).isoformat(), sha256=h)


def _d(v) -> date:
    return date.fromisoformat(str(v)[:10])


def collect(conn, cfg, start: date, end: date, max_signals=None, progress=None) -> dict:
    strat = LowVolatilityStrategy()
    sess = AsOfView(conn, end).sessions()
    sigs, rows = [], []
    t0 = time.time()
    for j, t in enumerate(sess):
        if t < start:
            continue
        view = AsOfView(conn, t)
        if not is_signal_session(view, t):
            continue
        if max_signals and len(sigs) >= max_signals:
            break
        ta = time.perf_counter()
        elig = list(eligible_symbols(view, cfg.universe))
        tb = time.perf_counter()
        s = strat.score(view, elig, t)
        tc = time.perf_counter()
        top = s["ranked"][:SPEC.params["top_n"]]
        gapset = set(s["window_gaps"])
        secs = [sector_for(r[0]) for r in top]
        sc = Counter(secs)
        vols = [r[1] for r in s["ranked"]]
        rows.append(dict(date=t, idx=j, eligible=s["n_eligible"], short=len(s["short"]), stale=len(s["stale"]), bad_price=len(s["bad_price"]), valid=len(s["valid"]),
                         window_gaps=len(gapset), zero_vol=len(s["zero_vol"]), proposed=len(top), zero_vol_in_top=sum(1 for r in top if r[1] == 0.0),
                         window_gaps_in_top=sum(1 for r in top if r[0] in gapset), distinct_sectors=len(sc), unknown_in_top=sc.get("UNKNOWN", 0),
                         max_same_sector=max(sc.values()) if sc else 0, structural_blocks=len(top) - len(sc),
                         vol_top_median=float(np.median([r[1] for r in top])) if top else None, vol_universe_median=float(np.median(vols)) if vols else None,
                         t_elig=tb - ta, t_score=tc - tb))
        sigs.append(dict(date=t, idx=j, top=[(r[0], r[1]) for r in top], sectors=secs))
        if progress:
            progress(len(sigs), t, time.time() - t0)
    return dict(sessions=sess, signals=sigs, rows=rows, seconds=time.time() - t0)


def occupancy(sessions, signals, max_positions, pos_pct, sector_cap, hold):
    """Mechanical model. Returns (entries, per-signal results)."""
    n = len(sessions)
    open_: list = []        # (symbol, exit_idx)
    entries, per = [], []
    for sg in signals:
        j = sg["idx"]
        open_ = [p for p in open_ if j < p[1]]
        held = {p[0] for p in open_}
        sec_n = Counter(sector_for(p[0]) for p in open_)
        free = max_positions - len(open_)
        start_open = len(open_)
        blocked_sector = blocked_held = no_slot = entered = 0
        for sym, _ in sg["top"]:
            if free <= 0:
                no_slot += 1
                continue
            if sym in held:
                blocked_held += 1
                continue
            sec = sector_for(sym)
            if (sec_n[sec] + 1) * pos_pct > sector_cap + 1e-9:
                blocked_sector += 1
                continue
            if j + 1 >= n:
                continue
            e = j + 1
            open_.append((sym, e + hold))
            entries.append(dict(symbol=sym, signal=sessions[j], entry=sessions[e], sector=sec))
            held.add(sym)
            sec_n[sec] += 1
            free -= 1
            entered += 1
        per.append(dict(date=sg["date"], open_at_signal=start_open, entered=entered, blocked_sector=blocked_sector, blocked_held=blocked_held, blocked_no_slot=no_slot,
                        open_after=len(open_)))
    return entries, per


def stats(v):
    if not len(v):
        return None
    a = np.asarray(v, dtype=float)
    return dict(median=float(np.median(a)), p5=float(np.percentile(a, 5)), p95=float(np.percentile(a, 95)), min=float(a.min()), max=float(a.max()), mean=float(a.mean()))


def summarise(res, cfg) -> dict:
    pr = cfg.portfolio_risk
    p = SPEC.params
    stop_dist_pct = (1.0 - p["stop_fraction"]) * 100.0
    pos_pct = pr.max_loss_pct_per_trade / stop_dist_pct * 100.0
    sessions, sigs, rows = res["sessions"], res["signals"], res["rows"]
    entries, per = occupancy(sessions, sigs, pr.max_concurrent_positions, pos_pct, pr.max_sector_exposure_pct, HOLD)
    by_year: dict = {}
    for r, q in zip(rows, per):
        by_year.setdefault(str(r["date"].year), []).append((r, q))
    by_year["ALL"] = list(zip(rows, per))
    gaps = [b["idx"] - a["idx"] for a, b in zip(sigs, sigs[1:])]            # sessions from one signal close to the next
    # sector cap alone (all slots free at every signal): how many of the top 25 fit
    fit = []
    for sg in sigs:
        sec_n, e = Counter(), 0
        for sym, _ in sg["top"]:
            s = sector_for(sym)
            if (sec_n[s] + 1) * pos_pct > pr.max_sector_exposure_pct + 1e-9:
                continue
            sec_n[s] += 1
            e += 1
            if e >= pr.max_concurrent_positions:
                break
        fit.append(e)
    out_years = {}
    for y, lst in by_year.items():
        rs, qs = [a for a, _ in lst], [b for _, b in lst]
        ent = [e for e in entries if y == "ALL" or str(e["entry"].year) == y]
        ps = lambda k, rr=rs: stats([r[k] for r in rr if r[k] is not None])    # noqa: E731
        pq = lambda k, qq=qs: stats([q[k] for q in qq])                          # noqa: E731
        out_years[y] = dict(signals=len(rs), first=str(rs[0]["date"]), last=str(rs[-1]["date"]), eligible=ps("eligible"), valid=ps("valid"), proposed=ps("proposed"),
                            distinct_sectors=ps("distinct_sectors"), structural_blocks=ps("structural_blocks"), max_same_sector=ps("max_same_sector"), unknown_in_top=ps("unknown_in_top"),
                            open_at_signal=pq("open_at_signal"), entered=pq("entered"), blocked_sector=pq("blocked_sector"), blocked_held=pq("blocked_held"), blocked_no_slot=pq("blocked_no_slot"),
                            signals_with_zero_entries=sum(1 for q in qs if q["entered"] == 0), window_gaps=ps("window_gaps"), window_gaps_in_top_total=sum(r["window_gaps_in_top"] for r in rs),
                            zero_vol=ps("zero_vol"), zero_vol_in_top_total=sum(r["zero_vol_in_top"] for r in rs), short=ps("short"), stale=ps("stale"), bad_price=ps("bad_price"),
                            entries=len(ent), distinct_symbols=len({e["symbol"] for e in ent}), vol_top_median=ps("vol_top_median"), vol_universe_median=ps("vol_universe_median"))
    entsec = Counter(e["sector"] for e in entries)
    c = Counter(e["symbol"] for e in entries)
    months = len(sigs)
    return dict(measured=str(date.today()), rule=dict(SPEC.params, exit_policy=SPEC.exit_policy), hold_sessions=HOLD,
                caps=dict(max_positions=pr.max_concurrent_positions, risk_pct=pr.max_loss_pct_per_trade, sector_cap_pct=pr.max_sector_exposure_pct,
                          max_total_risk_pct=pr.max_total_portfolio_risk_pct, stop_distance_pct=stop_dist_pct, position_pct_of_equity=pos_pct),
                signals=months, first_signal=str(sigs[0]["date"]), last_signal=str(sigs[-1]["date"]), calendar_last=str(sessions[-1]),
                gap_sessions_between_signals=dict(stats=stats(gaps), distribution=dict(sorted(Counter(gaps).items())), intervals_with_gap_le_hold=sum(1 for g in gaps if g <= HOLD),
                                                  intervals_total=len(gaps)),
                entries_total=len(entries), entries_per_month=len(entries) / months, entered_per_signal=stats([q["entered"] for q in per]),
                no_overlap_fit=stats(fit), no_overlap_fit_distribution=dict(sorted(Counter(fit).items())),
                sector_of_top25_all_signals=dict(Counter(s for sg in sigs for s in sg["sectors"]).most_common()), sector_of_entries=dict(entsec.most_common()),
                top_symbols=c.most_common(10), distinct_symbols=len(c), unknown_entries=entsec.get("UNKNOWN", 0), by_year=out_years,
                per_signal=[dict(date=str(r["date"]), **{k: v for k, v in r.items() if k not in ("date", "idx")}, **{k: v for k, v in q.items() if k != "date"})
                            for r, q in zip(rows, per)], run_seconds=res["seconds"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="signal_count_low_volatility.py", description="Counts-only signal study of the low_volatility rule (read-only on the lake; no returns computed).")
    ap.add_argument("--lake")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--max-signals", type=int)
    ap.add_argument("--out-json")
    ap.add_argument("--no-hash", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_shared_config()
    lp = Path(a.lake) if a.lake else lake_path()
    before = fingerprint(lp, not a.no_hash)
    conn = open_lake(a.lake)
    try:
        res = collect(conn, cfg, _d(a.start), _d(a.end), a.max_signals, lambda n, t, s: print(f"[{n}] {t} {s:.0f}s", file=sys.stderr, flush=True))
    finally:
        conn.close()
    after = fingerprint(lp, not a.no_hash)
    sm = summarise(res, cfg)
    sm["finsight_db"] = dict(before=before, after=after, unchanged=before == after)
    txt = json.dumps(sm, indent=1, default=str)
    if a.out_json:
        Path(a.out_json).write_text(txt, encoding="utf-8")
    else:
        print(txt)
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())
