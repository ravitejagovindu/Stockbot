"""Read-only dry run of the momentum_calm PAPER decision for past signal sessions (the first trading day of a month), on a fresh paper account (default 200,000 INR, no deposits).

  py -3 scripts/momentum_calm_paper_dryrun.py --date 2026-11-02 --out docs/strategies/momentum_calm/paper [--recent 2026-06-01,2026-07-01,...]

One ``engine.decide`` call per date on a fresh ``State.initial(cash)`` through the as-of view of the lake opened read-only; it writes NO state database, NO ticket file and sends no order. Output:
``dryrun_<date>.csv`` (the signal list: rank, symbol, reference price, stop, shares, risk, position value, sector), ``dryrun_<date>_blocked.csv`` (every blocked proposal and why) and
``dryrun_summary.md`` (account-size check across the dates). ASM/GSM ranges are not known for a past date and are passed empty (the live run reads the day's snapshot).
Refuses to start while a data job or run lock is held; it takes no lock itself and writes nothing in the lake."""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("STOCKBOT_NON_EQ", "held")

from stockbot.config.paths import lake_path  # noqa: E402
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import AsOfView  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.data.sector_map import SectorLookup  # noqa: E402
from stockbot.engine.decide import EventData, decide  # noqa: E402
from stockbot.engine.exit_policies.registry import policies_for  # noqa: E402
from stockbot.engine.types import State  # noqa: E402
from stockbot.strategies.momentum_calm.paper import PAPER_SPEC, paper_policy_extras, paper_strategy  # noqa: E402


def run_one(conn, cfg, d: date, cash: float) -> dict:
    strat = paper_strategy()
    policies = policies_for([strat.spec], extra=paper_policy_extras())
    dec, _ = decide(d, State.initial(cash), AsOfView(conn, d), [strat], cfg, EventData(sectors=SectorLookup(), asm_ranges={}), policies=policies, mode="paper")
    return {"date": d, "tickets": list(dec.new_tickets), "blocked": list(dec.blocked)}


def write_csvs(res: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    d = res["date"].isoformat()
    with open(out / f"dryrun_{d}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["signal_date", "rank", "symbol", "sector", "reference_price", "stop", "stop_pct", "shares", "risk_inr", "position_value_inr"])
        for t in res["tickets"]:
            w.writerow([d, t.rank, t.symbol, t.sector, round(t.reference_price, 2), round(t.stop, 2), round(100 * (1 - t.stop / t.reference_price), 2), t.shares_planned, round(t.risk_planned, 2), round(t.value_planned, 2)])
    with open(out / f"dryrun_{d}_blocked.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["signal_date", "strategy", "symbol", "reason", "stage"])
        for b in res["blocked"]:
            w.writerow([d, b.strategy_id, b.symbol, b.reason, b.stage])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="a past first trading day of a month")
    ap.add_argument("--recent", default="", help="comma-separated further signal dates for the account-size count")
    ap.add_argument("--cash", type=float, default=200000.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    from stockbot.data.guard.runlock import lock_dir
    held = sorted(p.name for p in lock_dir().glob("*.lock")) if lock_dir().exists() else []
    if held:
        print(f"LOCKED: {held}: nothing done")
        return 4
    cfg = load_shared_config()
    conn = open_lake(lake_path())
    dates = [date.fromisoformat(x) for x in [a.date] + [x for x in a.recent.split(",") if x]]
    rows, out = [], Path(a.out)
    for d in dates:
        res = run_one(conn, cfg, d, a.cash)
        write_csvs(res, out)
        sizing = [b for b in res["blocked"] if b.stage == "sizing"]
        zero = [b for b in sizing if b.reason == "SIZE_ZERO"]
        rows.append((d, len(res["tickets"]) + len(res["blocked"]), len(res["tickets"]), len(zero), len(res["blocked"]) - len(sizing), sum(t.value_planned for t in res["tickets"])))
        print(d, "proposals", rows[-1][1], "tickets", rows[-1][2], "size_zero", rows[-1][3], flush=True)
    with open(out / "dryrun_summary.md", "w", encoding="utf-8") as f:
        f.write(f"# momentum_calm paper dry run (read-only), account {a.cash:,.0f} INR, risk {cfg.portfolio_risk.max_loss_pct_per_trade}% per trade, {cfg.portfolio_risk.max_concurrent_positions} positions\n\n")
        f.write(f"Spec: status `{PAPER_SPEC.status}`, config hash `{PAPER_SPEC.config_hash()}`. Fresh account at each date (no earlier positions); no state written, no order sent.\n\n")
        f.write("| signal date | proposals (top 25 candidates) | tickets | skipped: size rounds to 0 | blocked at other stages (risk caps, overlay, series) | total ticket value INR |\n|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]:,.0f} |\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
