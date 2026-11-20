"""Descriptive side-by-side for momentum_calm_daily (read-only; recomputes NO result; decides nothing). Opens no database.

  py scripts/momentum_calm_daily_comparison.py --calm-daily docs/strategies/momentum_calm_daily/results_run1 --out-json <FILE> [--out-md <FILE>] [--ledger <family_ledger.csv>]

Columns: the stored any-day runs of family_batch4 (1.0% risk, EQ only, docs/strategies/riskadj_momentum_daily/results_run1), family_batch5 (1.0%, BE/BZ, results_run2_noneq) and family_batch6 (0.5% risk,
BE/BZ, docs/strategies/family_batch6/results/riskadj_momentum_daily), the monthly momentum_calm run of family_batch7 (docs/strategies/momentum_calm/results_run1) and the momentum_calm_daily run
(``--calm-daily DIR``: DIR/run, DIR/gates.json, DIR/family_results.json). Rows: trades, expectancy (net R), profit factor, max drawdown %, cash-credited alpha %, T1 adjusted p (2 / 3 month blocks), net
profit, FEES (the sum of ``costs`` over all closed trades of the stored trades.json), mean invested share, risk per trade %, BE/BZ switch, conclusion (all as stored, through
``family_batch6_comparison.summarise``), and the strategy's OWN WORST FALL (peak, trough, recovery) read from the stored ``run/equity_curve.json``. Nothing is recomputed from prices, no gate, hash,
verdict or ledger row is touched.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


MC = _load("momentum_calm_comparison")
C = MC.C
COLUMNS = (("family_batch4: any-day (1.0% risk, EQ only)", "family_batch4", "riskadj_momentum_daily", ROOT / "docs/strategies/riskadj_momentum_daily/results_run1"),
           ("family_batch5: any-day (1.0% risk, BE/BZ)", "family_batch5", "riskadj_momentum_daily", ROOT / "docs/strategies/riskadj_momentum_daily/results_run2_noneq"),
           ("family_batch6: any-day (0.5% risk, BE/BZ)", "family_batch6", "riskadj_momentum_daily", ROOT / "docs/strategies/family_batch6/results/riskadj_momentum_daily"),
           ("family_batch7: momentum_calm monthly (1.0% risk, BE/BZ)", "family_batch7", "momentum_calm", ROOT / "docs/strategies/momentum_calm/results_run1"))


def column(label: str, family_id: str, member: str, folder: Path, ledger: Path, fam_path=None) -> dict:
    col = MC.column(label, family_id, member, folder, ledger, fam_path=fam_path)
    trades = C._j(folder / "run" / "trades.json") or []
    col["summary"]["fees"] = sum(float(t.get("costs", 0.0)) for t in trades) if trades else None
    return col


ROWS = (("trades", "trades"), ("expectancy (net R)", "expectancy_r"), ("profit factor", "profit_factor"), ("max drawdown %", "max_drawdown_pct"), ("cash-credited alpha %", "cash_credited_alpha_pct"),
        ("T1 adjusted p (2 / 3 month blocks)", "t1_adjusted_p_by_block"), ("net profit", "net_profit"), ("fees (sum of trade costs)", "fees"), ("mean invested share", "mean_invested_share"),
        ("risk per trade %", "risk_per_trade_pct"), ("BE/BZ switch on", "non_eq_switch"), ("conclusion", "conclusion"))


def markdown(cols: list) -> str:
    out = ["### momentum_calm_daily against its four reference runs (stored numbers; DESCRIPTIVE, decides nothing)", "", "| item | " + " | ".join(c["label"] for c in cols) + " |", "|---|" + "---|" * len(cols)]
    out += [f"| {n} | " + " | ".join(C._fmt(c["summary"][k]) for c in cols) + " |" for n, k in ROWS]
    out.append("| worst fall (peak to trough; recovery) | " + " | ".join(MC.fmt_fall(c["summary"]["worst_fall"]) for c in cols) + " |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--calm-daily", required=True, help="the momentum_calm_daily result folder (run/, baseline/, gates.json, family_results.json)")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md")
    ap.add_argument("--ledger", default=str(C.LEDGER))
    ap.add_argument("--reference-root", help="test hook: replace the repository root in the reference folders")
    a = ap.parse_args(argv)
    ledger = Path(a.ledger)
    cols = []
    for label, fam, member, folder in COLUMNS:
        if a.reference_root:
            folder = Path(a.reference_root) / folder.relative_to(ROOT)
        cols.append(column(label, fam, member, folder, ledger))
    d = Path(a.calm_daily)
    cols.append(column("family_batch8: momentum_calm_daily (1.0% risk, BE/BZ)", "family_batch8", "momentum_calm_daily", d, ledger, fam_path=d / "family_results.json"))
    Path(a.out_json).write_text(json.dumps({"columns": cols}, indent=1, default=str), encoding="utf-8")
    md = markdown(cols)
    if a.out_md:
        Path(a.out_md).write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
