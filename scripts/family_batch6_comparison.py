"""Descriptive side-by-side for family_batch6 (read-only; recomputes NO result; decides nothing).

  py scripts/family_batch6_comparison.py --batch6 docs/strategies/family_batch6/results --out-json <FILE> [--out-md <FILE>]

For each member of family_batch6 (``<batch6>/riskadj_momentum`` and ``<batch6>/riskadj_momentum_daily``, each with run/ baseline/ gates.json) it prints the stored numbers beside those of the
earlier registered runs of the same strategy: riskadj_momentum -> family_batch2 (docs/strategies/riskadj_momentum/results_run1); riskadj_momentum_daily -> family_batch4
(docs/strategies/riskadj_momentum_daily/results_run1) and family_batch5 (docs/strategies/riskadj_momentum_daily/results_run2_noneq). Numbers come from the stored gates.json, trades.json and from the
FAMILY_RESULTS rows of the family ledger (T1 adjusted p-values and the conclusion); nothing is recomputed and no database is opened.
Columns: trades, expectancy (net R), profit factor, max drawdown %, cash-credited alpha %, T1 adjusted p (2 and 3 month blocks), net profit, mean invested share, risk per trade.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "stockbot" / "validation" / "ledger" / "records" / "family_ledger.csv"
EARLIER = {"riskadj_momentum": [("family_batch2 (EQ only, 1.0% risk)", "family_batch2", ROOT / "docs/strategies/riskadj_momentum/results_run1")],
           "riskadj_momentum_daily": [("family_batch4 (EQ only, 1.0% risk)", "family_batch4", ROOT / "docs/strategies/riskadj_momentum_daily/results_run1"),
                                      ("family_batch5 (BE/BZ, 1.0% risk)", "family_batch5", ROOT / "docs/strategies/riskadj_momentum_daily/results_run2_noneq")]}


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def ledger_results(family_id: str, member: str, ledger: Path = LEDGER):
    """The stored FAMILY_RESULTS entry of ``member`` in ``family_id`` (T1 p-values, conclusion), or None."""
    if not ledger.exists():
        return None
    with open(ledger, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["family_id"] == family_id and r["row_type"] == "FAMILY_RESULTS"]
    if not rows:
        return None
    return json.loads(rows[-1]["results_json"]).get(member)


def summarise(folder: Path, family_id: str | None, member: str, ledger: Path = LEDGER, fam_path: Path | None = None) -> dict:
    trades = _j(folder / "run" / "trades.json") or []
    man = _j(folder / "run" / "manifest.json") or {}
    gates = _j(folder / "gates.json") or {}
    g = {r["gate"]: r["observed"] for r in gates.get("gates", [])}
    fam = _j(fam_path or folder / "family_results.json") or (ledger_results(family_id, member, ledger) if family_id else None) or {}
    t1 = {b: v.get(member, {}).get("adjusted_p_value") for b, v in (fam.get("T1", {}).get("blocks", {}) or {}).items()}
    ro = (man.get("risk_override") or {}).get("max_loss_pct_per_trade")
    return {"folder": str(folder), "trades": len(trades), "expectancy_r": g.get("min_expectancy_r"), "profit_factor": g.get("min_profit_factor"), "max_drawdown_pct": g.get("max_drawdown_pct"),
            "cash_credited_alpha_pct": g.get("min_alpha_pct"), "t1_adjusted_p_by_block": t1, "net_profit": sum(t["net_pnl"] for t in trades) if trades else None,
            "mean_invested_share": (gates.get("counts") or {}).get("invested_share_mean"), "risk_per_trade_pct": ro if ro is not None else 1.0,
            "non_eq_switch": bool(man.get("non_eq_view")), "conclusion": (fam.get("conclusion") or {}).get(member)}


ROWS = (("trades", "trades"), ("expectancy (net R)", "expectancy_r"), ("profit factor", "profit_factor"), ("max drawdown %", "max_drawdown_pct"), ("cash-credited alpha %", "cash_credited_alpha_pct"),
        ("T1 adjusted p (2 / 3 month blocks)", "t1_adjusted_p_by_block"), ("net profit", "net_profit"), ("mean invested share", "mean_invested_share"), ("risk per trade %", "risk_per_trade_pct"),
        ("BE/BZ switch on", "non_eq_switch"), ("conclusion", "conclusion"))


def _fmt(v):
    if isinstance(v, dict):
        return " / ".join(str(v.get(b)) for b in ("2", "3")) if v else "-"
    if isinstance(v, float):
        return f"{v:.4f}"
    return "-" if v is None else str(v)


def markdown(tables: dict) -> str:
    out = []
    for member, cols in tables.items():
        out += [f"### {member}", "", "| item | " + " | ".join(c["label"] for c in cols) + " |", "|---|" + "---|" * len(cols)]
        out += [f"| {n} | " + " | ".join(_fmt(c["summary"][k]) for c in cols) + " |" for n, k in ROWS]
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--batch6", required=True, help="folder holding riskadj_momentum/ and riskadj_momentum_daily/ (each run/ baseline/ gates.json)")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md")
    ap.add_argument("--ledger", default=str(LEDGER))
    a = ap.parse_args(argv)
    ledger = Path(a.ledger)
    tables = {}
    for member, earlier in EARLIER.items():
        cols = [{"label": lab, "summary": summarise(folder, fam, member, ledger)} for lab, fam, folder in earlier]
        cols.append({"label": "family_batch6 (BE/BZ, 0.5% risk)", "summary": summarise(Path(a.batch6) / member, "family_batch6", member, ledger, fam_path=Path(a.batch6) / "family_results.json")})
        tables[member] = cols
    Path(a.out_json).write_text(json.dumps(tables, indent=1, default=str), encoding="utf-8")
    md = markdown(tables)
    if a.out_md:
        Path(a.out_md).write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
