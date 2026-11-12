"""COUNTS-ONLY signal study for trend_breakout_100d (Stage 1). A study tool, NOT the strategy: the signals come from the strategy itself (TrendBreakoutStrategy with top_n lifted so
that every signal is returned), the shared eligibility rule comes from stockbot.universe, and the near_52w_high overlap comes from the existing near_52w_high study tool.

  py scripts/signal_count_trend_breakout_100d.py [--lake PATH] [--start 2016-01-01] [--end 2026-10-16] [--out-json F] [--out-md F] [--no-hash]
  py scripts/signal_count_trend_breakout_100d.py --part-out part1.json --start A --end B        # score a date segment only (the cache), for parallel processes
  py scripts/signal_count_trend_breakout_100d.py --assemble part1.json part2.json ... --out-md F # join cached segments, run the occupancy models, write the report; opens no database

Reports (all counts): eligible names, signals and proposed (top 25) per session; the share of signals that are ALSO near_52w_high candidates the same day (nearness >= 0.95 and that rule's
gap guard, via near_high_signal_count.snapshot); signals per Nifty regime (Nifty close above / not above its own 200-session mean); a mechanical occupancy model of the 12-position cap
under ASSUMED fixed holds (the real exit, a 15% trailing stop, depends on later prices, which this study never reads), with and without the shared 15% sector cap; runtime.
It never computes or reads a return, P&L or any price after the signal date. Every session is evaluated through AsOfView(conn, t), so no later bar can be read. The lake is opened only
through stockbot.data.lake.open_lake (mode=ro); the file's sha256 is taken before and after.
"""
import argparse
import dataclasses
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.config.paths import lake_path  # noqa: E402
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import AsOfView  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.data_checks import near_high_signal_count as NH  # noqa: E402
from stockbot.strategies.trend_breakout_100d import SPEC, TrendBreakoutStrategy  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402

DEFAULT_START, DEFAULT_END = "2016-01-01", "2026-10-16"        # window A (the near_52w_high window; the family window)
HOLDS = (20, 40, 60, 100, 150, 250)                            # ASSUMED fixed holds for the occupancy model (sessions); NOT the real exit
MAX_POSITIONS, RISK_PCT, SECTOR_CAP_PCT = 12, 1.0, 15.0        # shared values (portfolio_risk); read from the shared config in main()
REGIME_SMA = 200
WIDE = dataclasses.replace(SPEC, params={**SPEC.params, "top_n": 10 ** 6})      # the same rule, every signal returned
REGIMES = ("above", "below", "n/a")


def _d(v) -> date:
    return date.fromisoformat(str(v)[:10])


def regime_of(view: AsOfView) -> str:
    """Nifty close above its own 200-session mean (today included), measured at the signal close; 'n/a' while fewer than 200 Nifty bars exist."""
    b = view.index_bars(lookback=REGIME_SMA)["close_raw"]
    if len(b) < REGIME_SMA:
        return "n/a"
    return "above" if float(b.iloc[-1]) > float(b.mean()) else "below"


def score_session(conn, t: date, eligible_fn) -> dict:
    view = AsOfView(conn, t)
    ta = time.perf_counter()
    elig = list(eligible_fn(view))
    tb = time.perf_counter()
    props, _ = TrendBreakoutStrategy(WIDE).propose(view, elig, t, {}, {})
    tc = time.perf_counter()
    syms = [p.symbol for p in props]                                     # all signals, in rank order (ADTV desc, symbol)
    nh = NH.snapshot(view, syms)                                         # near_52w_high rule applied to the signal names only
    nh_set = {s for s, _ in nh["ranked"]}
    return dict(date=t, eligible=len(elig), signals=len(syms), proposed=min(len(syms), SPEC.params["top_n"]), top=syms[:SPEC.params["top_n"]], overlap_all=sum(1 for s in syms if s in nh_set),
                overlap_top=sum(1 for s in syms[:SPEC.params["top_n"]] if s in nh_set), regime=regime_of(view), t_elig=tb - ta, t_score=tc - tb, signal_syms=syms)


def collect_part(conn, eligible_fn, *, start, end, max_sessions=None, progress=None) -> dict:
    sess = [d for d in AsOfView(conn, end).sessions() if d >= start]
    if max_sessions:
        sess = sess[:max_sessions]
    rows, ever, t0 = [], set(), time.time()
    for j, t in enumerate(sess):
        r = score_session(conn, t, eligible_fn)
        ever.update(r.pop("signal_syms"))
        rows.append(r)
        if progress and (j % 50 == 0 or j == len(sess) - 1):
            progress(j + 1, len(sess), t, time.time() - t0)
    return dict(sessions=sess, rows=rows, ever_signalled=sorted(ever), seconds=time.time() - t0)


def part_to_json(part: dict) -> dict:
    return dict(sessions=[d.isoformat() for d in part["sessions"]], rows=[{**r, "date": r["date"].isoformat()} for r in part["rows"]], ever_signalled=part["ever_signalled"], seconds=part["seconds"])


def part_from_json(d: dict) -> dict:
    return dict(sessions=[_d(x) for x in d["sessions"]], rows=[{**r, "date": _d(r["date"])} for r in d["rows"]], ever_signalled=list(d["ever_signalled"]), seconds=d["seconds"])


def merge_parts(parts) -> dict:
    parts = sorted(parts, key=lambda p: p["sessions"][0])
    for a, b in zip(parts, parts[1:]):
        if not a["sessions"][-1] < b["sessions"][0]:
            raise ValueError(f"segments overlap: {a['sessions'][-1]} and {b['sessions'][0]}")
    return dict(sessions=[d for p in parts for d in p["sessions"]], rows=[r for p in parts for r in p["rows"]], ever_signalled=sorted(set().union(*[set(p["ever_signalled"]) for p in parts])),
                seconds=sum(p["seconds"] for p in parts))


def occupancy(rows, hold, *, pos_pct=None, sector_cap_pct=None) -> NH.Occupancy:
    occ = NH.Occupancy(len(rows), MAX_POSITIONS, hold=hold, pos_pct=pos_pct, sector_cap_pct=sector_cap_pct)
    for j, r in enumerate(rows):
        occ.step(j, [(s, 0.0) for s in r["top"]])
    return occ


def _stats(v):
    if not len(v):
        return None
    a = np.asarray(v, dtype=float)
    return dict(median=float(np.median(a)), p5=float(np.percentile(a, 5)), p95=float(np.percentile(a, 95)), min=float(a.min()), max=float(a.max()), mean=float(a.mean()))


def summarise(part: dict, measured=None) -> dict:
    rows, sess = part["rows"], part["sessions"]
    n = len(rows)
    pos_pct = RISK_PCT / ((1.0 - SPEC.params["stop_fraction"]) * 100.0) * 100.0
    groups: dict = {}
    for r in rows:
        groups.setdefault(str(r["date"].year), []).append(r)
    groups["ALL (sample)"] = rows
    out_groups = {}
    for g, rs in groups.items():
        sig_total, ov_total = sum(r["signals"] for r in rs), sum(r["overlap_all"] for r in rs)
        top_total, ovt_total = sum(r["proposed"] for r in rs), sum(r["overlap_top"] for r in rs)
        out_groups[g] = dict(sessions=len(rs), first=str(rs[0]["date"]), last=str(rs[-1]["date"]), eligible=_stats([r["eligible"] for r in rs]), signals=_stats([r["signals"] for r in rs]),
                             proposed=_stats([r["proposed"] for r in rs]), sessions_with_signal=sum(1 for r in rs if r["signals"] > 0), sessions_with_12=sum(1 for r in rs if r["signals"] >= MAX_POSITIONS),
                             signal_name_sessions=sig_total, overlap_signals=ov_total, overlap_share=(ov_total / sig_total) if sig_total else None,
                             proposed_name_sessions=top_total, overlap_proposed=ovt_total, overlap_share_proposed=(ovt_total / top_total) if top_total else None,
                             t_elig=_stats([r["t_elig"] for r in rs]), t_score=_stats([r["t_score"] for r in rs]))
    regimes = {}
    for k in REGIMES:
        rs = [r for r in rows if r["regime"] == k]
        sg, ov = sum(r["signals"] for r in rs), sum(r["overlap_all"] for r in rs)
        regimes[k] = dict(sessions=len(rs), share_of_sessions=(len(rs) / n) if n else None, signal_name_sessions=sg, share_of_signals=(sg / sum(r["signals"] for r in rows)) if rows and sum(r["signals"] for r in rows) else None,
                          signals_per_session=_stats([r["signals"] for r in rs]), proposed_per_session=_stats([r["proposed"] for r in rs]), sessions_with_signal=sum(1 for r in rs if r["signals"] > 0),
                          sessions_with_12=sum(1 for r in rs if r["signals"] >= MAX_POSITIONS), overlap_share=(ov / sg) if sg else None)
    by_year_regime = {}
    for r in rows:
        k = (str(r["date"].year), r["regime"])
        by_year_regime.setdefault(k, [0, 0])
        by_year_regime[k][0] += 1
        by_year_regime[k][1] += r["signals"]
    months = n / 21.0
    models = {}
    for h in HOLDS:
        for label, kw in (("no sector cap", {}), ("sector cap 15%", dict(pos_pct=pos_pct, sector_cap_pct=SECTOR_CAP_PCT))):
            o = occupancy(rows, h, **kw)
            ents = [dict(symbol=e[0], signal=sess[e[1]], entry=sess[e[2]]) for e in o.entries]
            reg_of = {r["date"]: r["regime"] for r in rows}
            by_reg = Counter(reg_of[e["signal"]] for e in ents)
            by_year = Counter(str(e["entry"].year) for e in ents)
            conc = Counter(e["symbol"] for e in ents)
            models[f"hold {h} / {label}"] = dict(hold=h, variant=label, entries=len(ents), per_month=(len(ents) / months) if months else None, entries_by_signal_regime=dict(by_reg),
                                                 entries_by_year=dict(sorted(by_year.items())), sessions_full=sum(1 for x in o.occupancy if x >= MAX_POSITIONS),
                                                 mean_open=float(np.mean(o.occupancy)) if o.occupancy else None, distinct_symbols=len(conc),
                                                 top_symbol=conc.most_common(1)[0] if conc else None, sector_blocks_total=sum(o.blocks),
                                                 unrealised_signals_on_last_session=o.unrealised_signals)
    return dict(measured=str(measured or date.today()), rule=SPEC.params, exit_policy=SPEC.exit_policy, params=dict(max_positions=MAX_POSITIONS, risk_pct=RISK_PCT, sector_cap_pct=SECTOR_CAP_PCT,
                position_pct_of_equity=pos_pct), calendar=dict(first_session=str(sess[0]), last_session=str(sess[-1]), n_sessions=n), groups=out_groups, regimes=regimes,
                signals_by_year_regime={f"{y} {k}": dict(sessions=v[0], signal_name_sessions=v[1]) for (y, k), v in sorted(by_year_regime.items())}, occupancy_models=models,
                distinct_names_ever_signalled=len(part["ever_signalled"]), run_seconds=part["seconds"])


def _f(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


def render_markdown(sm: dict) -> str:
    m = sm["measured"]
    L = [f"# trend_breakout_100d signal-count study (counts only) - measured {m}", "",
         f"Window evaluated: {sm['calendar']['first_session']} to {sm['calendar']['last_session']} ({sm['calendar']['n_sessions']} sessions). Rule: {json.dumps(sm['rule'])}; exit policy {sm['exit_policy']}. "
         f"Caps: {json.dumps(sm['params'])}.", ""]

    def stat_table(title, key, note=""):
        L.append(f"## {title} (measured {m})")
        if note:
            L.append(note)
        L.extend(["", "| period | sessions | median | p5 | p95 | min | max | mean |", "|---|---|---|---|---|---|---|---|"])
        for g, G in sm["groups"].items():
            s = G[key]
            if s:
                L.append(f"| {g} | {G['sessions']} | {_f(s['median'])} | {_f(s['p5'])} | {_f(s['p95'])} | {_f(s['min'], 0)} | {_f(s['max'], 0)} | {_f(s['mean'])} |")
        L.append("")

    stat_table("(1) Eligible names per session (shared eligibility)", "eligible")
    stat_table("(2) Signals per session (close > max of prior 100 closes AND close > SMA200, data rule met)", "signals")
    stat_table("(3) Names proposed per session (top 25 by ADTV)", "proposed")
    L += [f"## (4) Sessions with signals (measured {m})", "", "| period | sessions | with >=1 signal | with >= 12 signals | signal name-sessions |", "|---|---|---|---|---|"]
    for g, G in sm["groups"].items():
        L.append(f"| {g} | {G['sessions']} | {G['sessions_with_signal']} | {G['sessions_with_12']} | {G['signal_name_sessions']} |")
    L += ["", f"## (5) Overlap with near_52w_high (measured {m})", "",
          "A signal counts as 'also near_52w_high eligible' if, on the same day, that rule's candidate test passes for the same name: shared eligibility, the 252-bar gap guard, and adjusted close >= 0.95 x the "
          "highest adjusted close of the last 252 bars (`near_high_signal_count.snapshot`). It is NOT whether the name was in that strategy's top 25 (that ranking is a separate, "
          "smaller set). 'Proposed' columns restrict this strategy's side to its own top 25.", "",
          "| period | signal name-sessions | also near-high candidate | share | proposed name-sessions | also near-high candidate | share |", "|---|---|---|---|---|---|---|"]
    for g, G in sm["groups"].items():
        L.append(f"| {g} | {G['signal_name_sessions']} | {G['overlap_signals']} | {_f(G['overlap_share'] * 100 if G['overlap_share'] is not None else None)}% | {G['proposed_name_sessions']} | "
                 f"{G['overlap_proposed']} | {_f(G['overlap_share_proposed'] * 100 if G['overlap_share_proposed'] is not None else None)}% |")
    L += ["", f"## (6) Signals by market regime (measured {m})", "",
          "Regime = Nifty (NIFTY50_INDEX) close above / not above the mean of its last 200 closes, on the signal day; 'n/a' = fewer than 200 Nifty bars in the lake.", "",
          "| regime | sessions | share of sessions | signal name-sessions | share of signals | signals/session median | p5 | p95 | mean | sessions >=1 signal | sessions >=12 | overlap with near-high |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, R in sm["regimes"].items():
        s = R["signals_per_session"]
        L.append(f"| {k} | {R['sessions']} | {_f(R['share_of_sessions'] * 100 if R['share_of_sessions'] is not None else None)}% | {R['signal_name_sessions']} | "
                 f"{_f(R['share_of_signals'] * 100 if R['share_of_signals'] is not None else None)}% | {_f(s['median']) if s else '-'} | {_f(s['p5']) if s else '-'} | {_f(s['p95']) if s else '-'} | "
                 f"{_f(s['mean']) if s else '-'} | {R['sessions_with_signal']} | {R['sessions_with_12']} | {_f(R['overlap_share'] * 100 if R['overlap_share'] is not None else None)}% |")
    L += ["", "By year and regime (sessions / signal name-sessions):", "", "| year regime | sessions | signal name-sessions |", "|---|---|---|"]
    for k, v in sm["signals_by_year_regime"].items():
        L.append(f"| {k} | {v['sessions']} | {v['signal_name_sessions']} |")
    L += ["", f"## (7) Trade-rate estimate: mechanical occupancy model (measured {m})", "",
          "The real exit is `trailing_pct_15` (a stop that trails 15% under the highest close since entry, plus the 15% initial stop). How long a position lives depends on later prices, which this "
          "study does NOT read, so the hold is ASSUMED at fixed lengths and the table is a bracket, not a forecast. Every free slot (12 max) is filled from the day's top 25 at the next open; a "
          "symbol already held is skipped; stops, the 15% total-risk cap, costs, the gap-up cap, the cash cap and missing-bar blocks are ignored. Position size at the fixed 15% stop and 1% risk "
          f"= {sm['params']['position_pct_of_equity']:.2f}% of equity.", "",
          "| assumed hold (sessions) | variant | entries in sample | per month | sessions at 12 slots | mean open | distinct names | most-used name | sector blocks | entries by signal regime |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, M in sm["occupancy_models"].items():
        L.append(f"| {M['hold']} | {M['variant']} | {M['entries']} | {_f(M['per_month'], 2)} | {M['sessions_full']} | {_f(M['mean_open'])} | {M['distinct_symbols']} | {M['top_symbol']} | "
                 f"{M['sector_blocks_total']} | {json.dumps(M['entries_by_signal_regime'])} |")
    L += ["", "Entries per year under each assumed hold (no sector cap):", "", "| hold | " + " | ".join(sorted({y for M in sm["occupancy_models"].values() for y in M["entries_by_year"]})) + " |",
          "|---|" + "---|" * len({y for M in sm["occupancy_models"].values() for y in M["entries_by_year"]})]
    years = sorted({y for M in sm["occupancy_models"].values() for y in M["entries_by_year"]})
    for h in HOLDS:
        M = sm["occupancy_models"][f"hold {h} / no sector cap"]
        L.append(f"| {h} | " + " | ".join(str(M["entries_by_year"].get(y, 0)) for y in years) + " |")
    L += ["", f"Distinct names that signalled at least once: {sm['distinct_names_ever_signalled']}.", ""]
    stat_table("(8a) Seconds to apply the shared eligibility rule, one session", "t_elig")
    stat_table("(8b) Seconds to score one session with the strategy (all eligible names)", "t_score")
    L.append(f"Whole run {sm['run_seconds']:.0f} s of process time for {sm['calendar']['n_sessions']} sessions (summed over segments).")
    return "\n".join(L) + "\n"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="signal_count_trend_breakout_100d.py", description="Counts-only signal study of trend_breakout_100d (read-only on the lake; no returns are computed).")
    ap.add_argument("--lake", help="path of finsight.db (default: STOCKBOT_DB or <repo>/finsight.db)")
    ap.add_argument("--start", default=DEFAULT_START, help="first session, YYYY-MM-DD")
    ap.add_argument("--end", default=DEFAULT_END, help="last session, YYYY-MM-DD")
    ap.add_argument("--max-sessions", type=int, help="evaluate only the first N sessions (smoke test)")
    ap.add_argument("--part-out", help="score the sessions only and write the per-session counts and top-25 lists (the cache) as JSON")
    ap.add_argument("--assemble", nargs="+", metavar="PART", help="no database: join cached parts and write the report")
    ap.add_argument("--out-json", help="write the summary as JSON")
    ap.add_argument("--out-md", help="write the report as markdown (default: print)")
    ap.add_argument("--no-hash", action="store_true", help="skip the sha256 of the database file (size and mtime are still compared)")
    return ap


def _emit(sm: dict, tail: str, args) -> None:
    md = render_markdown(sm) + tail
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(sm, indent=1, default=str), encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")
    else:
        print(md)


def main(argv=None) -> int:
    global MAX_POSITIONS, RISK_PCT, SECTOR_CAP_PCT
    args = build_parser().parse_args(argv)
    cfg = load_shared_config()
    MAX_POSITIONS, RISK_PCT, SECTOR_CAP_PCT = cfg.portfolio_risk.max_concurrent_positions, cfg.portfolio_risk.max_loss_pct_per_trade, cfg.portfolio_risk.max_sector_exposure_pct
    if args.assemble:
        parts = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.assemble]
        sm = summarise(merge_parts([part_from_json(p) for p in parts]))
        fps = [p["finsight_db"] for p in parts]
        sm["finsight_db"] = dict(parts=fps, unchanged=all(f["unchanged"] for f in fps))
        tail = "\n" + "\n".join(f"part {i}: before {json.dumps(f['before'])}\n        after  {json.dumps(f['after'])}\n        unchanged: {f['unchanged']}" for i, f in enumerate(fps)) + "\n"
        _emit(sm, tail, args)
        return 0 if sm["finsight_db"]["unchanged"] else 1
    lp = Path(args.lake) if args.lake else lake_path()
    before = NH.fingerprint(lp, with_hash=not args.no_hash) if lp.exists() else None
    conn = open_lake(args.lake)
    progress = lambda i, n, t, s: print(f"[{i}/{n}] {t} {s:.0f}s", file=sys.stderr, flush=True)   # noqa: E731
    try:
        part = collect_part(conn, lambda v: eligible_symbols(v, cfg.universe), start=_d(args.start), end=_d(args.end), max_sessions=args.max_sessions, progress=progress)
    finally:
        conn.close()
    after = NH.fingerprint(lp, with_hash=not args.no_hash)
    fp = dict(before=before, after=after, unchanged=(before == after))
    if args.part_out:
        out = part_to_json(part)
        out["finsight_db"] = fp
        Path(args.part_out).write_text(json.dumps(out, default=str), encoding="utf-8")
        return 0 if fp["unchanged"] else 1
    sm = summarise(part)
    sm["finsight_db"] = fp
    _emit(sm, f"\nfinsight.db before: {json.dumps(before)}\nfinsight.db after:  {json.dumps(after)}\nunchanged: {before == after}\n", args)
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())
