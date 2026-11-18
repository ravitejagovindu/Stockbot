"""Side-by-side of two riskadj_momentum_daily result folders (family_batch4 run 1 and the BE/BZ re-run, family_batch5): read-only, NO recomputation of any result.

  py scripts/noneq_comparison_riskadj_momentum_daily.py --old docs/strategies/riskadj_momentum_daily/results_run1 --new docs/strategies/riskadj_momentum_daily/results_run2_noneq \
        --lake "$STOCKBOT_DB" --out-json <FILE> [--out-md <FILE>]

Both folders have the layout run/ baseline/ gates.json family_results.json benchmark.json. Reads their stored files and the lake (open_lake, read-only) only to find, for every closed trade, the sessions in
which its symbol traded in a non-EQ series (market_data_non_eq: BE/BZ/BL...) between entry and exit. Writes the table the pre-registration (PREREGISTRATION_NONEQ.md) lists. Nothing is selected,
tuned or concluded here: the verdict of each run is the one its own validate_family output gives.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.data import non_eq  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def non_eq_days(con, symbol: str, entry: str, exit_: str) -> list:
    """Non-EQ bars (date, series) of ``symbol`` from the entry date to the exit date inclusive; empty when the table does not exist."""
    if con.execute("select 1 from sqlite_master where type='table' and name=?", (non_eq.TABLE,)).fetchone() is None:
        return []
    marks = ",".join("?" * len(non_eq.BAR_SERIES))
    return con.execute(f"select trade_date, series from {non_eq.TABLE} where symbol=? and trade_date>=? and trade_date<=? and series in ({marks}) order by trade_date",
                       (symbol, entry[:10], exit_[:10], *non_eq.BAR_SERIES)).fetchall()


def summarise(folder: Path, con) -> dict:
    trades = _j(folder / "run" / "trades.json") or []
    man = _j(folder / "run" / "manifest.json") or {}
    gates = _j(folder / "gates.json") or {}
    fam = _j(folder / "family_results.json") or {}
    g = {r["gate"]: r["observed"] for r in gates.get("gates", [])}
    reasons: dict = {}
    for t in trades:
        reasons[t.get("exit_reason_engine") or t["exit_reason"]] = reasons.get(t.get("exit_reason_engine") or t["exit_reason"], 0) + 1
    held, exits_in_non_eq = [], 0
    for t in trades:
        days = non_eq_days(con, t["symbol"], str(t["entry_date"]), str(t["exit_date"]))
        if days:
            held.append({"symbol": t["symbol"], "entry_date": str(t["entry_date"])[:10], "exit_date": str(t["exit_date"])[:10], "exit_reason": t["exit_reason"], "non_eq_sessions": len(days),
                         "first_non_eq": days[0][0], "series": sorted({d[1] for d in days}), "net_pnl": t["net_pnl"]})
            if days[-1][0] == str(t["exit_date"])[:10]:
                exits_in_non_eq += 1
    t1 = {b: {m: v.get("adjusted_p_value") for m, v in ms.items()} for b, ms in (fam.get("T1", {}).get("blocks", {}) or {}).items()}
    return {"folder": str(folder), "trades": len(trades), "symbol_no_bars_exits": reasons.get("SYMBOL_NO_BARS", 0), "exit_reasons": reasons, "exits_on_a_non_eq_bar": exits_in_non_eq,
            "trades_held_through_a_non_eq_spell": len(held), "net_profit": sum(t["net_pnl"] for t in trades), "expectancy_r": g.get("min_expectancy_r"), "profit_factor": g.get("min_profit_factor"),
            "max_drawdown_pct": g.get("max_drawdown_pct"), "cash_credited_alpha_pct": g.get("min_alpha_pct"), "t1_adjusted_p_by_block": t1, "conclusion": fam.get("conclusion"),
            "non_eq_view": man.get("non_eq_view"), "non_eq_events": man.get("non_eq_events"), "held_list": held}


def markdown(old: dict, new: dict) -> str:
    rows = [("trades", "trades"), ("SYMBOL_NO_BARS exits", "symbol_no_bars_exits"), ("exits on a BE/BZ bar", "exits_on_a_non_eq_bar"), ("trades held through a BE/BZ spell", "trades_held_through_a_non_eq_spell"),
            ("expectancy (net R)", "expectancy_r"), ("profit factor", "profit_factor"), ("max drawdown %", "max_drawdown_pct"), ("cash-credited alpha %", "cash_credited_alpha_pct"),
            ("net profit", "net_profit"), ("T1 adjusted p by block", "t1_adjusted_p_by_block"), ("conclusion", "conclusion")]
    L = ["| item | family_batch4 run 1 | family_batch5 (BE/BZ) |", "|---|---|---|"] + [f"| {n} | {old[k]} | {new[k]} |" for n, k in rows]
    ev = (new.get("non_eq_events") or {})
    L += [f"| SELL_CAPPED_NON_EQ events | n/a | {ev.get('sell_capped_non_eq')} |", "", "Trades of the new run that held a stock through a BE/BZ spell:", "",
          "| symbol | entry | exit | exit reason | non-EQ sessions | first | series |", "|---|---|---|---|---|---|---|"]
    L += [f"| {h['symbol']} | {h['entry_date']} | {h['exit_date']} | {h['exit_reason']} | {h['non_eq_sessions']} | {h['first_non_eq']} | {','.join(h['series'])} |" for h in new["held_list"]]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--lake", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md")
    a = ap.parse_args(argv)
    con = open_lake(a.lake)
    try:
        old, new = summarise(Path(a.old), con), summarise(Path(a.new), con)
    finally:
        con.close()
    Path(a.out_json).write_text(json.dumps({"old": old, "new": new}, indent=1, default=str), encoding="utf-8")
    if a.out_md:
        Path(a.out_md).write_text(markdown(old, new), encoding="utf-8")
    print(markdown(old, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
