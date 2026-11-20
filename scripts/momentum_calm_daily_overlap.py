"""DESCRIPTIVE OVERLAP CHECK for momentum_calm_daily (stage 1). Counts and symbol lists only: it computes NO return, P&L, win rate or equity of any kind, and reads no price after a signal date.

  STOCKBOT_VIEW=memory py scripts/momentum_calm_daily_overlap.py [--lake PATH] [--start 2016-01-01] [--end 2026-10-16] [--step 21] [--out-json docs/strategies/momentum_calm_daily/OVERLAP.json] [--out-md docs/strategies/momentum_calm_daily/OVERLAP.md]

Every session is a signal session for the any-day rule, so the check SAMPLES: the first session whose 252-session calendar window exists (on or after --start) and then every 21st session after it (--step 21), up to
--end. This keeps the check fast; it is a sample of sessions, not all of them. For each sampled session, through ``AsOfView(conn, t)``:
  (a) eligible names (the shared eligibility function);
  (b) calm names: names with a sigma252 (history guards of the rule) whose sigma252 <= the median of sigma252 over ALL of those names (ties at the median are calm);
  (c) candidates after r12 > 0 (every other riskadj_momentum_daily condition included): among the calm names, and among all names;
  (d) the picks of momentum_calm_daily (top 25 of the calm candidates, or fewer) and of plain riskadj_momentum_daily (its own proposals) as the PURE top 25 by the same ranking: no cooldown (no strategy state),
      no slots, no cash, no caps;
  (e) overlap = |momentum_calm_daily picks intersect riskadj_momentum_daily picks| / 25.
PRE-DECLARED RULE (fixed before the number was seen): mean overlap over the sampled sessions > 0.85 means the idea is not different enough and the work stops after this report.
The lake is opened only through ``open_lake`` (mode=ro); the run lock and the database check before and after come from ``short_step``.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import AsOfView, active_view_name  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.strategies.momentum_calm_daily.strategy import SPEC, screen  # noqa: E402
from stockbot.strategies.riskadj_momentum_daily import SPEC as PLAIN_SPEC, RiskAdjMomentumDailyStrategy  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402

THRESHOLD = 0.85                       # fixed by the owner before any number was seen
TOP_N = int(SPEC.params["top_n"])
LABEL = "DESCRIPTIVE, NO RETURN OF ANY KIND IS COMPUTED"


def one_session(view, cfg, plain) -> dict:
    t = view.as_of
    elig = list(eligible_symbols(view, cfg.universe))
    s = screen(view, elig, t, SPEC.params, cooling=None, calm=True)
    if s is None:
        return {"date": t.isoformat(), "window": False}
    m = [c[0] for c in s["ordered"][:TOP_N]]
    a = [x.symbol for x in plain.propose(view, elig, t, {}, {})[0]]
    return {"date": t.isoformat(), "window": True, "eligible": s["eligible"], "with_sigma252": s["sigma_n"], "median_sigma252": s["median"], "calm": s["calm_n"],
            "positive_calm": s["positive_calm"], "positive_all": s["positive_all"], "calm_picks": m, "plain_picks": a, "overlap_names": len(set(m) & set(a)), "overlap": len(set(m) & set(a)) / TOP_N}


def summarise(rows: list) -> dict:
    ov = [r["overlap"] for r in rows]
    pc = [r["positive_calm"] for r in rows]
    mean_ov = mean(ov) if ov else None
    return {"sampled_sessions": len(rows), "overlap": {"mean": mean_ov, "median": median(ov) if ov else None, "min": min(ov) if ov else None, "max": max(ov) if ov else None},
            "sampled_sessions_with_fewer_than_25_calm_candidates": sum(1 for x in pc if x < TOP_N), "sampled_sessions_with_no_calm_candidate": sum(1 for x in pc if x == 0),
            "sampled_sessions_with_fewer_than_25_plain_picks": sum(1 for r in rows if len(r["plain_picks"]) < TOP_N),
            "calm_candidates": {"min": min(pc) if pc else None, "median": median(pc) if pc else None, "max": max(pc) if pc else None},
            "calm_share_of_names_with_sigma252": {"median": median(r["calm"] / r["with_sigma252"] for r in rows if r["with_sigma252"]) if rows else None},
            "rule": {"threshold": THRESHOLD, "mean_overlap_above_threshold": bool(mean_ov is not None and mean_ov > THRESHOLD),
                     "outcome": ("STOP: the idea is not different enough (mean overlap > %.2f); no pre-registration is written" % THRESHOLD) if (mean_ov is not None and mean_ov > THRESHOLD)
                     else "CONTINUE: mean overlap is %.2f or below" % THRESHOLD}}


def markdown(rows: list, summ: dict, meta: dict) -> str:
    o, c = summ["overlap"], summ["calm_candidates"]
    L = [f"# momentum_calm_daily: overlap with riskadj_momentum_daily ({LABEL})", "",
         f"Window {meta['window'][0]} to {meta['window'][1]}. **Sample: the first session with a 252-session window and every {meta['step']}th session after it** (every session is a signal session for the any-day rule; the check samples to stay fast): "
         f"{summ['sampled_sessions']} sampled sessions; spec hash `{meta['spec_config_hash']}`; asof_view `{meta['asof_view']}`.",
         "No return, P&L, win rate or equity is computed here. Overlap = |momentum_calm_daily picks ∩ riskadj_momentum_daily picks| / 25, picks being the pure top 25 on that date (no cooldown, slots, cash or caps).", "",
         "## Result", "",
         f"- mean overlap **{o['mean']:.4f}**, median {o['median']:.4f}, min {o['min']:.4f}, max {o['max']:.4f}",
         f"- sampled sessions with fewer than 25 calm candidates (calm and r12 > 0): {summ['sampled_sessions_with_fewer_than_25_calm_candidates']} (with none: {summ['sampled_sessions_with_no_calm_candidate']}); "
         f"with fewer than 25 plain picks: {summ['sampled_sessions_with_fewer_than_25_plain_picks']}",
         f"- calm candidates per sampled session (calm and r12 > 0): min {c['min']}, median {c['median']}, max {c['max']}",
         f"- pre-declared rule: mean overlap > {THRESHOLD} stops the work. **{summ['rule']['outcome']}**", "",
         "## Per sampled session", "",
         "| date | eligible | with sigma252 | calm | calm and r12>0 | all r12>0 | calm picks | plain picks | overlap names | overlap |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['date']} | {r['eligible']} | {r['with_sigma252']} | {r['calm']} | {r['positive_calm']} | {r['positive_all']} | {len(r['calm_picks'])} | {len(r['plain_picks'])} | {r['overlap_names']} | {r['overlap']:.2f} |")
    return "\n".join(L) + "\n"


def sample(sessions: list, start: date, end: date, step: int, first_window_index: int = 251) -> list:
    """The sampled sessions: the first session on or after ``start`` that has at least ``first_window_index`` + 1 sessions of calendar up to it, then every ``step``-th after it, up to ``end``."""
    idx = [i for i, d in enumerate(sessions) if d >= start and i >= first_window_index]
    if not idx:
        return []
    return [d for d in sessions[idx[0]::step] if d <= end]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lake", help="path of finsight.db (default: STOCKBOT_DB or <repo>/finsight.db); opened read-only")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--step", type=int, default=21)
    ap.add_argument("--out-json", default=str(ROOT / "docs" / "strategies" / "momentum_calm_daily" / "OVERLAP.json"))
    ap.add_argument("--out-md", default=str(ROOT / "docs" / "strategies" / "momentum_calm_daily" / "OVERLAP.md"))
    ap.add_argument("--max-sessions", type=int)
    args = ap.parse_args(argv)
    from stockbot.config.paths import lake_path
    cfg = load_shared_config()
    conn = open_lake(Path(args.lake) if args.lake else lake_path())
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    sessions = list(AsOfView(conn, end).sessions())
    picked = sample(sessions, start, end, args.step)
    if args.max_sessions:
        picked = picked[:args.max_sessions]
    plain, rows, skipped = RiskAdjMomentumDailyStrategy(), [], []
    for k, d in enumerate(picked):
        r = one_session(AsOfView(conn, d), cfg, plain)
        if not r["window"]:
            skipped.append(r["date"])
            continue
        rows.append(r)
        print(f"{k + 1}/{len(picked)} {d} eligible {r['eligible']} calm {r['calm']} calm+r12>0 {r['positive_calm']} overlap {r['overlap_names']}/{TOP_N}", flush=True)
    conn.close()
    summ = summarise(rows)
    meta = {"window": [start.isoformat(), end.isoformat()], "step": args.step, "spec_config_hash": SPEC.config_hash(), "plain_spec_config_hash": PLAIN_SPEC.config_hash(), "asof_view": active_view_name(),
            "sampled_sessions_without_a_252_session_window": skipped, "label": LABEL}
    out = {"meta": meta, "summary": summ, "rows": rows}
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(out, indent=1), encoding="utf-8")
    Path(args.out_md).write_text(markdown(rows, summ, meta), encoding="utf-8")
    print(json.dumps(summ, indent=1))
    return 0


from stockbot.data.guard.runcheck import short_step  # noqa: E402
main = short_step("momentum_calm_daily_overlap (short step)")(main)      # run lock and database check before and after


if __name__ == "__main__":
    sys.exit(main())
