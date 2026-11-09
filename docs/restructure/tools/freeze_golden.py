"""docs/restructure/tools/freeze_golden.py - Phase 10 step 1: freeze what the OLD engine path (engine_core.candidate_builder) produces, BEFORE engine_core is deleted.

Writes under tests/golden/:
  asof_120_samples.json         the 120 (symbol, eval_date) samples of the as-of equivalence test (rng seed 7, 40 symbols x 3 dates): row counts and sha256 of the exact
                                float64 bytes of the raw frame and of the adjusted frame as build_candidate_dicts returned them
  engine_scan.csv               copy of the STOP-4 engine scan result (docs/restructure/baseline/engine_scan_restructure_stop4.csv)
  engine_scan_summary.json      764 -> 267 (499 removed, 2 created), names scanned, residual categories
  verification_old_path.csv     the 57 verification rows with the engine factor the old path gave (docs/data_audit/verification_engine_path.csv)
  SHA256SUMS                    sha256 of every file above
Read-only on finsight.db. Run once; the files are committed.
"""
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
GOLD = ROOT / "tests" / "golden"


def frame_hash(df: pd.DataFrame) -> str:
    return hashlib.sha256(np.ascontiguousarray(df.to_numpy(dtype="float64")).tobytes() + "|".join(map(str, df.index)).encode()).hexdigest()


def main() -> int:
    from engine_core.candidate_builder import build_candidate_dicts
    from stockbot.data.asof import AsOfView
    from stockbot.data.lake import open_lake
    from stockbot.data_checks.f2_engine_scan import session_for

    GOLD.mkdir(parents=True, exist_ok=True)
    db = ROOT / "finsight.db"
    conn, orm = open_lake(db), session_for(str(db))
    cfg = {"data": {"resistance_lookback_days": 252}}
    syms = [r[0] for r in conn.execute("select symbol from market_data_lake group by symbol having count(*) >= 300 order by symbol")]
    syms = [s for s in syms if s not in ("NIFTY50_INDEX", "INDIA_VIX")]
    rng = np.random.default_rng(7)
    sample = list(rng.choice(syms, size=40, replace=False))
    out = []
    bad = 0
    for sym in sample:
        dates = [date.fromisoformat(r[0]) for r in conn.execute("select trade_date from market_data_lake where symbol=? order by trade_date", (sym,))]
        for k in rng.choice(len(dates), size=3, replace=False):
            d = dates[int(k)]
            cand = build_candidate_dicts(orm, cfg, [sym], d)
            if not cand:
                continue
            raw, adj = cand[0]["raw_ohlcv"], cand[0]["adjusted_ohlcv"]
            v = AsOfView(conn, d)
            same = frame_hash(v.raw_bars(sym, len(raw))) == frame_hash(raw) and frame_hash(v.adjusted_bars(sym, len(raw))) == frame_hash(adj)
            bad += 0 if same else 1
            out.append({"symbol": sym, "eval_date": d.isoformat(), "lookback": len(raw), "raw_sha256": frame_hash(raw), "adj_sha256": frame_hash(adj),
                        "raw_last_close": float(raw["close_raw"].iloc[-1]), "adj_first_close": float(adj["close_adj"].iloc[0]), "adj_last_close": float(adj["close_adj"].iloc[-1])})
    print(f"{len(out)} samples frozen; bit-exact view vs old path: {len(out) - bad} of {len(out)}")
    if bad:
        print("the view is not bit-identical on some samples: the golden test must use a tolerance; stopping")
        return 1
    (GOLD / "asof_120_samples.json").write_text(json.dumps({"rng_seed": 7, "symbols": 40, "dates_per_symbol": 3, "samples": out}, indent=1), encoding="utf-8")

    base = ROOT / "docs" / "restructure" / "baseline"
    scan_csv = (base / "engine_scan_restructure_stop4.csv").read_bytes()
    (GOLD / "engine_scan.csv").write_bytes(scan_csv)
    md = (base / "engine_scan_restructure_stop4.md").read_text(encoding="utf-8")
    num = lambda pat: int(re.search(pat + r"\s*:\s*(\d+)", md).group(1))
    summary = {"names_scanned": int(re.search(r"Names scanned:\s*(\d+)", md).group(1)), "large_before": num(r"large moves before adjustment"), "large_after": num(r"large moves after adjustment"),
               "removed": num(r"removed by adjusting"), "created": num(r"created by adjusting"), "as_of": "2026-09-30", "threshold": 0.40, "min_price": 5.0}
    rdf = pd.read_csv(base / "engine_scan_restructure_stop4.csv")
    summary["remaining_by_category"] = {k: int(v) for k, v in rdf.groupby("category").size().items()}
    (GOLD / "engine_scan_summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8")
    (GOLD / "verification_old_path.csv").write_bytes((ROOT / "docs" / "data_audit" / "verification_engine_path.csv").read_bytes())

    sums = []
    for f in sorted(GOLD.iterdir()):
        if f.name != "SHA256SUMS":
            sums.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
    (GOLD / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print("\n".join(sums))
    return 0


if __name__ == "__main__":
    sys.exit(main())
