"""Descriptive side-by-side for momentum_calm (read-only; recomputes NO result; decides nothing). Opens no database.

  py scripts/momentum_calm_comparison.py --calm docs/strategies/momentum_calm/results_run1 --out-json <FILE> [--out-md <FILE>] [--ledger <family_ledger.csv>]

Columns: the stored runs of family_batch2 (monthly momentum, 1.0% risk, EQ only, docs/strategies/riskadj_momentum/results_run1), family_batch6 (monthly momentum at 0.5% risk, BE/BZ held,
docs/strategies/family_batch6/results/riskadj_momentum), family_batch3 (low volatility inside an uptrend, docs/strategies/lowvol_uptrend/results_run1) and the momentum_calm run
(``--calm DIR``: DIR/run, DIR/gates.json, DIR/family_results.json). Rows: trades, expectancy (net R), profit factor, max drawdown %, cash-credited alpha %, T1 adjusted p (2 / 3 month blocks), net profit,
mean invested share, risk per trade %, BE/BZ switch, conclusion (all as stored, through ``family_batch6_comparison.summarise``), and the strategy's OWN WORST FALL: peak date, trough date, depth and
recovery date of its deepest equity drawdown, read from the stored ``run/equity_curve.json`` (a descriptive reading of the stored curve; the gate value stays the stored ``max_drawdown_pct``).
Nothing is recomputed from prices, no gate, hash, verdict or ledger row is touched.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _cmp():
    spec = importlib.util.spec_from_file_location("family_batch6_comparison", ROOT / "scripts" / "family_batch6_comparison.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = _cmp()
COLUMNS = (("family_batch2: riskadj_momentum (1.0% risk, EQ only)", "family_batch2", "riskadj_momentum", ROOT / "docs/strategies/riskadj_momentum/results_run1"),
           ("family_batch6: riskadj_momentum (0.5% risk, BE/BZ)", "family_batch6", "riskadj_momentum", ROOT / "docs/strategies/family_batch6/results/riskadj_momentum"),
           ("family_batch3: lowvol_uptrend (1.0% risk, EQ only)", "family_batch3", "lowvol_uptrend", ROOT / "docs/strategies/lowvol_uptrend/results_run1"))


def worst_fall(curve: dict) -> dict:
    """The deepest peak-to-trough fall of a stored equity curve {date: equity}: peak date, trough date, depth in percent and the first later date at or above the peak (None if never)."""
    days = sorted(curve)
    peak_d, peak_v, best = None, 0.0, {"depth_pct": 0.0, "peak": None, "trough": None, "recovery": None}
    for d in days:
        v = float(curve[d])
        if peak_d is None or v > peak_v:
            peak_d, peak_v = d, v
        dd = 100.0 * (peak_v - v) / peak_v if peak_v > 0 else 0.0
        if dd > best["depth_pct"]:
            best = {"depth_pct": dd, "peak": peak_d, "trough": d, "recovery": None, "_peak_v": peak_v}
    if best["peak"] is not None:
        later = [d for d in days if d > best["trough"] and float(curve[d]) >= best["_peak_v"]]
        best["recovery"] = later[0] if later else None
    best.pop("_peak_v", None)
    return best


def column(label: str, family_id: str, member: str, folder: Path, ledger: Path, fam_path=None) -> dict:
    s = C.summarise(folder, family_id, member, ledger, fam_path=fam_path)
    eq = C._j(folder / "run" / "equity_curve.json")
    s["worst_fall"] = worst_fall(eq) if eq else None
    return {"label": label, "summary": s}


def fmt_fall(w) -> str:
    return "-" if not w or w["peak"] is None else f"{w['depth_pct']:.1f}% ({str(w['peak'])[:10]} to {str(w['trough'])[:10]}; recovered {str(w['recovery'])[:10] if w['recovery'] else 'no'})"


def markdown(cols: list) -> str:
    out = ["### momentum_calm against its three reference runs (stored numbers; DESCRIPTIVE, decides nothing)", "", "| item | " + " | ".join(c["label"] for c in cols) + " |", "|---|" + "---|" * len(cols)]
    out += [f"| {n} | " + " | ".join(C._fmt(c["summary"][k]) for c in cols) + " |" for n, k in C.ROWS]
    out.append("| worst fall (peak to trough; recovery) | " + " | ".join(fmt_fall(c["summary"]["worst_fall"]) for c in cols) + " |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--calm", required=True, help="the momentum_calm result folder (run/, baseline/, gates.json, family_results.json)")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md")
    ap.add_argument("--ledger", default=str(C.LEDGER))
    ap.add_argument("--reference-root", help="test hook: replace the repository root in the three reference folders")
    a = ap.parse_args(argv)
    ledger = Path(a.ledger)
    cols = []
    for label, fam, member, folder in COLUMNS:
        if a.reference_root:
            folder = Path(a.reference_root) / folder.relative_to(ROOT)
        cols.append(column(label, fam, member, folder, ledger))
    calm = Path(a.calm)
    cols.append(column("family_batch7: momentum_calm (1.0% risk, BE/BZ)", "family_batch7", "momentum_calm", calm, ledger, fam_path=calm / "family_results.json"))
    Path(a.out_json).write_text(json.dumps({"columns": cols}, indent=1, default=str), encoding="utf-8")
    md = markdown(cols)
    if a.out_md:
        Path(a.out_md).write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
