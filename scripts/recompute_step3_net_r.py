"""scripts/recompute_step3_net_r.py — F1: derive explicit gross/net/after-tax R columns for the Step 3 outputs.

Reads the existing Step 3 trade CSVs (``backtest/outputs/trades_candidate_CFG-0x.csv``), recomputes
``risk_inr``, ``gross_r``, ``net_r``, ``net_r_after_tax`` with ``stockbot.validation.trade_metrics.add_r_columns`` and writes
them to a NEW folder (default ``backtest/outputs_recomputed_net``). Old outputs and the trial ledger are never modified.
Equity curves and random-baseline files are copied unchanged.

IMPORTANT: the source data are the flawed Yahoo-adjusted prices (see the F2 finding). The comparison table therefore
only shows the gross-versus-net effect; it is NOT a valid strategy result.

Usage:  py -3 scripts/recompute_step3_net_r.py [--out DIR]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stockbot.risk.r_metrics import add_r_columns  # noqa: E402

SRC = ROOT / "backtest" / "outputs"
CFGS = [f"CFG-0{i}" for i in range(1, 7)]


def recompute(out_dir: Path) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for cid in CFGS:
        src = SRC / f"trades_candidate_{cid}.csv"
        df = pd.read_csv(src)
        old_net = df["net_r"].copy()  # the legacy orphan column
        df = df.drop(columns=["net_r"])
        new = add_r_columns(df)
        for name in (f"trades_candidate_{cid}.csv", f"trades_{cid}_pooled.csv"):
            new.to_csv(out_dir / name, index=False)
        for suffix in ("window_2020_2021", "window_2022_2026"):
            shutil.copy2(SRC / f"equity_{cid}_{suffix}.csv", out_dir / f"equity_{cid}_{suffix}.csv")
        pnl_pos = new.loc[new["net_r"] > 0, "net_r"].sum()
        pnl_neg = -new.loc[new["net_r"] < 0, "net_r"].sum()
        old_pos, old_neg = old_net[old_net > 0].sum(), -old_net[old_net < 0].sum()
        rows.append({
            "config": cid, "trades": len(new),
            "legacy_net_r_mean": old_net.mean(), "gross_r_mean": new["gross_r"].mean(),
            "net_r_mean": new["net_r"].mean(), "net_r_after_tax_mean": new["net_r_after_tax"].mean(),
            "legacy_PF": old_pos / old_neg if old_neg else float("inf"),
            "net_PF": pnl_pos / pnl_neg if pnl_neg else float("inf"),
            "legacy_equals_gross": bool((old_net - new["gross_r"]).abs().max() < 1e-9),
        })
    for extra in SRC.glob("apples_to_apples_random_trades*.csv"):
        shutil.copy2(extra, out_dir / extra.name)
    table = pd.DataFrame(rows)
    table.to_csv(out_dir / "recompute_comparison.csv", index=False)
    return table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "backtest" / "outputs_recomputed_net"))
    args = ap.parse_args()
    t = recompute(Path(args.out))
    print("COMPUTED ON FLAWED YAHOO-ADJUSTED DATA - shows gross-vs-net effect only, not valid results\n")
    print(t.to_string(index=False))


if __name__ == "__main__":
    main()
