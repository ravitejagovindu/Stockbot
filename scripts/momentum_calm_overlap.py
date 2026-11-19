"""DESCRIPTIVE OVERLAP CHECK for momentum_calm (stage 1). Counts and symbol lists only: it computes NO return, P&L, win rate or equity of any kind, and reads no price after a signal date.

  STOCKBOT_VIEW=memory py scripts/momentum_calm_overlap.py [--lake PATH] [--start 2016-01-01] [--end 2026-10-16] [--out-json docs/strategies/momentum_calm/OVERLAP.json] [--out-md docs/strategies/momentum_calm/OVERLAP.md]

For every monthly signal session (first trading session of a calendar month, the strategies' own ``is_signal_session``) whose 252-session calendar window exists, through ``AsOfView(conn, t)``:
  (a) eligible names (the shared eligibility function);
  (b) calm names: names with a sigma252 (history guards of the rule) whose sigma252 <= the median of sigma252 over ALL of those names (ties at the median are calm);
  (c) candidates after r12 > 0 (every other riskadj_momentum condition included): among the calm names, and among all names;
  (d) the picks of momentum_calm (top 25 of the calm candidates, or fewer) and of plain riskadj_momentum (the pure top 25 by the same ranking function, no slots, cash or caps);
  (e) overlap = |momentum_calm picks intersect riskadj_momentum picks| / 25.
PRE-DECLARED RULE (fixed before the number was seen): mean overlap over all signal months > 0.85 means the idea is not different enough and the work stops after this report.
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
from stockbot.strategies.momentum_calm.strategy import SPEC, is_signal_session, screen  # noqa: E402
from stockbot.strategies.riskadj_momentum import SPEC as PLAIN_SPEC, RiskAdjMomentumStrategy  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402

THRESHOLD = 0.85                       # fixed by the owner before any number was seen
TOP_N = int(SPEC.params["top_n"])
LABEL = "DESCRIPTIVE, NO RETURN OF ANY KIND IS COMPUTED"


def one_month(view, cfg, plain) -> dict:
    t = view.as_of
    elig = list(eligible_symbols(view, cfg.universe))
    s = screen(view, elig, t, SPEC.params, calm=True)
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
    return {"signal_months": len(rows), "overlap": {"mean": mean_ov, "median": median(ov) if ov else None, "min": min(ov) if ov else None, "max": max(ov) if ov else None},
            "months_with_fewer_than_25_calm_candidates": sum(1 for x in pc if x < TOP_N), "months_with_no_calm_candidate": sum(1 for x in pc if x == 0),
            "months_with_fewer_than_25_plain_picks": sum(1 for r in rows if len(r["plain_picks"]) < TOP_N),
            "calm_candidates": {"min": min(pc) if pc else None, "median": median(pc) if pc else None, "max": max(pc) if pc else None},
            "calm_share_of_names_with_sigma252": {"median": median(r["calm"] / r["with_sigma252"] for r in rows if r["with_sigma252"]) if rows else None},
            "rule": {"threshold": THRESHOLD, "mean_overlap_above_threshold": bool(mean_ov is not None and mean_ov > THRESHOLD),
                     "outcome": ("STOP: the idea is not different enough (mean overlap > %.2f); no pre-registration is written" % THRESHOLD) if (mean_ov is not None and mean_ov > THRESHOLD)
                     else "CONTINUE: mean overlap is %.2f or below" % THRESHOLD}}


def markdown(rows: list, summ: dict, meta: dict) -> str:
    o, c = summ["overlap"], summ["calm_candidates"]
    L = [f"# momentum_calm: overlap with riskadj_momentum ({LABEL})", "",
         f"Window {meta['window'][0]} to {meta['window'][1]}; monthly signal sessions with a 252-session window: {summ['signal_months']}; spec hash `{meta['spec_config_hash']}`; asof_view `{meta['asof_view']}`.",
         "No return, P&L, win rate or equity is computed here. Overlap = |momentum_calm picks ∩ riskadj_momentum picks| / 25, picks being the pure top 25 on that date (no slots, cash or caps).", "",
         "## Result", "",
         f"- mean overlap **{o['mean']:.4f}**, median {o['median']:.4f}, min {o['min']:.4f}, max {o['max']:.4f}",
         f"- months with fewer than 25 calm candidates: {summ['months_with_fewer_than_25_calm_candidates']} (with none: {summ['months_with_no_calm_candidate']}); plain riskadj_momentum months with fewer than 25 picks: {summ['months_with_fewer_than_25_plain_picks']}",
         f"- calm candidates per month (calm and r12 > 0): min {c['min']}, median {c['median']}, max {c['max']}",
         f"- pre-declared rule: mean overlap > {THRESHOLD} stops the work. **{summ['rule']['outcome']}**", "",
         "## Per signal date", "",
         "| date | eligible | with sigma252 | calm | calm and r12>0 | all r12>0 | calm picks | plain picks | overlap names | overlap |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['date']} | {r['eligible']} | {r['with_sigma252']} | {r['calm']} | {r['positive_calm']} | {r['positive_all']} | {len(r['calm_picks'])} | {len(r['plain_picks'])} | {r['overlap_names']} | {r['overlap']:.2f} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lake", help="path of finsight.db (default: STOCKBOT_DB or <repo>/finsight.db); opened read-only")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--out-json", default=str(ROOT / "docs" / "strategies" / "momentum_calm" / "OVERLAP.json"))
    ap.add_argument("--out-md", default=str(ROOT / "docs" / "strategies" / "momentum_calm" / "OVERLAP.md"))
    ap.add_argument("--max-months", type=int)
    args = ap.parse_args(argv)
    from stockbot.config.paths import lake_path
    cfg = load_shared_config()
    conn = open_lake(Path(args.lake) if args.lake else lake_path())
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    sessions = [d for d in AsOfView(conn, end).sessions() if start <= d <= end]
    months = [d for d in sessions if is_signal_session(AsOfView(conn, d))]
    if args.max_months:
        months = months[:args.max_months]
    plain, rows, skipped = RiskAdjMomentumStrategy(), [], []
    for k, d in enumerate(months):
        r = one_month(AsOfView(conn, d), cfg, plain)
        if not r["window"]:
            skipped.append(r["date"])
            continue
        rows.append(r)
        print(f"{k + 1}/{len(months)} {d} eligible {r['eligible']} calm {r['calm']} calm+r12>0 {r['positive_calm']} overlap {r['overlap_names']}/{TOP_N}", flush=True)
    conn.close()
    summ = summarise(rows)
    meta = {"window": [start.isoformat(), end.isoformat()], "spec_config_hash": SPEC.config_hash(), "plain_spec_config_hash": PLAIN_SPEC.config_hash(), "asof_view": active_view_name(),
            "months_without_a_252_session_window": skipped, "label": LABEL}
    out = {"meta": meta, "summary": summ, "rows": rows}
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(out, indent=1), encoding="utf-8")
    Path(args.out_md).write_text(markdown(rows, summ, meta), encoding="utf-8")
    print(json.dumps(summ, indent=1))
    return 0


from stockbot.data.guard.runcheck import short_step  # noqa: E402
main = short_step("momentum_calm_overlap (short step)")(main)      # run lock and database check before and after


if __name__ == "__main__":
    sys.exit(main())
