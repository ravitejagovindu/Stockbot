"""B1 baseline for the short_term_reversal validation: matched random entries through the shared simulator and the library exit.

  py scripts/baseline_matched_random_short_term_reversal.py --lake PATH --run-dir DIR --out-dir NEW_DIR [--draws 20] [--min-filled 10] [--seed 20261111] [--no-hash]

For every usable trade of the run (not END_OF_WINDOW, not excluded_ca), on the SAME signal session, 20 symbols are drawn at random (seed 20261111) from the shared-eligible pool of that date, never the
trade's own symbol, no pool filter, no ASM ranges. Each draw gets the actual trade's relative stop distance applied to its own signal close and is simulated with ``simulate_ticket`` and the library
policy named in the strategy spec (fixed_hold_5): the same next-open fill, slippage, gap rule, corporate-action rebasing, stepping, costs and exit as the strategy (stockbot.validation.random_baseline.
draw_matched_random, unchanged). A pair needs at least ``min_filled`` filled draws; short pairs are counted, and more than 5% of trades losing their pair is flagged. There are no portfolio effects.

Reads: eligibility and each draw's path (bars up to its own exit); forward returns for the secondary test T2 only up to 20 sessions after the entry, blanked when a split or bonus falls inside that
horizon (raw closes are used, as in the shared helper). The shared helper's unbounded forward read is capped by ``ForwardCappedView``. Writes actual_trades.csv, baseline_draws.csv, baseline_meta.json.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.adjustments import action_factor  # noqa: E402
from stockbot.data.asof import DEFAULT_LOOKBACK, AsOfView, active_view_name  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.engine.exit_policies.registry import resolve  # noqa: E402
from stockbot.risk.r_metrics import compute_trade_r  # noqa: E402
from stockbot.strategies.short_term_reversal import SPEC  # noqa: E402
from stockbot.validation.random_baseline import draw_matched_random  # noqa: E402

DRAWS, MIN_FILLED, SEED, MAX_H = 20, 10, 20261111, 20
HORIZONS = (1, 5, 10, 20)
LOSS_FLAG = 0.05
SUBPERIODS = (("2016-2019", date(2016, 1, 1), date(2019, 12, 31)), ("2020-2026", date(2020, 1, 1), date(2026, 12, 31)))


def window_label(d: date) -> str:
    for tag, lo, hi in SUBPERIODS:
        if lo <= d <= hi:
            return tag
    return SUBPERIODS[-1][0] if d > SUBPERIODS[-1][2] else SUBPERIODS[0][0]


class ForwardCappedView(AsOfView):
    """An as-of view whose open-ended forward read (``raw_bars(symbol, None, start=entry)``, how the shared ``forward_returns_pct`` works) stops MAX_H sessions after ``start``."""

    def __init__(self, conn, as_of, sessions):
        super().__init__(conn, as_of)
        self._sessions = list(sessions)
        self._pos = {d: i for i, d in enumerate(self._sessions)}

    def raw_bars(self, symbol, lookback=DEFAULT_LOOKBACK, start=None, end=None):
        if lookback is None and start is not None and end is None and start in self._pos:
            end = self._sessions[min(self._pos[start] + MAX_H, len(self._sessions) - 1)]
        return super().raw_bars(symbol, lookback, start, end)


def forward_returns_bounded(conn, sessions, symbol: str, entry_date: date, entry_price: float) -> dict:
    """Percent move of the raw close h sessions after the entry session, from the fill price, h in HORIZONS. Reads nothing after entry + MAX_H sessions. NaN when the history ends first or when a
    split or bonus (an adjusted action) falls inside the horizon."""
    nan = {f"ret_{h}": float("nan") for h in HORIZONS}
    pos = {d: i for i, d in enumerate(sessions)}
    i = pos.get(entry_date)
    if i is None:
        return nan
    end = sessions[min(i + MAX_H, len(sessions) - 1)]
    view = AsOfView(conn, end)
    try:
        if any(entry_date < a["ex_date"] <= end and action_factor(a) != 1.0 for a in view.corporate_actions(symbol)):
            return nan
    except ValueError:
        return nan
    b = view.raw_bars(symbol, lookback=None, start=entry_date, end=end)
    after = [float(c) for d, c in b["close_raw"].items() if d > entry_date]
    return {f"ret_{h}": ((after[h - 1] / entry_price - 1.0) * 100.0 if len(after) >= h else float("nan")) for h in HORIZONS}


def run_baseline(lake, run_dir, out_dir, *, draws: int = DRAWS, min_filled: int = MIN_FILLED, seed: int = SEED, shared_config=None) -> dict:
    cfg = shared_config or load_shared_config()
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"refusing to write into a non-empty directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    trades = json.loads((run_dir / "trades.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    last_day = date.fromisoformat(manifest["window"][1])
    use = [t for t in trades if t["exit_reason"] != "END_OF_WINDOW" and not t.get("excluded_ca", False)]
    conn = open_lake(lake)
    try:
        sessions = AsOfView(conn, last_day).sessions()
        pos = {d: i for i, d in enumerate(sessions)}
        final = sessions[-1]

        def view_at(d):
            return ForwardCappedView(conn, d, sessions) if d == final else AsOfView(conn, d)

        actual = pd.DataFrame([{"unique_trade_id": t["position_id"], "symbol": t["symbol"], "entry_date": date.fromisoformat(t["entry_date"]), "entry_price": float(t["entry_price"]),
                                "stop": float(t["initial_stop"]), "window": window_label(date.fromisoformat(t["entry_date"]))} for t in use])
        if actual.empty:
            d = pd.DataFrame()
        else:
            d = draw_matched_random(actual, sessions=sessions, view_at=view_at, shared_config=cfg, policy=resolve(SPEC.exit_policy), equity=cfg.backtest.initial_equity,
                                    draws_per_trade=draws, seed=seed)
        unfilled = dict(d.attrs.get("unfilled", {}))
        if len(d):
            fr = [forward_returns_bounded(conn, sessions, r.symbol, r.entry_date, r.entry_price) for r in d.itertuples(index=False)]
            for h in HORIZONS:
                d[f"ret_{h}"] = [x[f"ret_{h}"] for x in fr]
        rows = []
        for t in use:
            ed, xd = date.fromisoformat(t["entry_date"]), date.fromisoformat(t["exit_date"])
            r = compute_trade_r(entry_price=t["entry_price"], stop=t["initial_stop"], shares_initial=t["shares_initial"], pnl_gross=t["gross_pnl"], pnl_net=t["net_pnl"], risk_inr=t["risk_inr"])
            rows.append({"unique_trade_id": t["position_id"], "symbol": t["symbol"], "window": window_label(ed), "entry_date": ed, "exit_date": xd, "entry_price": t["entry_price"],
                         "stop": t["initial_stop"], "gross_r": r["gross_r"], "net_r": r["net_r"], "days_held": pos[xd] - pos[ed] if ed in pos and xd in pos else float("nan"),
                         **forward_returns_bounded(conn, sessions, t["symbol"], ed, t["entry_price"])})
    finally:
        conn.close()
    a = pd.DataFrame(rows)
    counts = d.groupby("matched_trade_id").size() if len(d) else pd.Series(dtype=int)
    kept = int((counts >= min_filled).sum())
    dropped = len(use) - kept
    share = dropped / len(use) if use else 0.0
    meta = {"draws_per_trade": draws, "min_filled": min_filled, "seed": seed, "policy": SPEC.exit_policy, "usable_trades": len(use), "pairs_kept": kept, "dropped_pairs": dropped,
            "share_dropped": share, "flag": (f"more than 5% of trades lost their pair ({share:.1%}): the result is flagged" if share > LOSS_FLAG else None), "draws_total": int(len(d)),
            "unfilled": unfilled, "end_of_window": sum(1 for t in trades if t["exit_reason"] == "END_OF_WINDOW"), "excluded_ca": sum(1 for t in trades if t.get("excluded_ca", False)),
            "window": manifest["window"], "spec_config_hash": SPEC.config_hash(), "asof_view": active_view_name()}
    for name, frame in (("actual_trades.csv", a), ("baseline_draws.csv", d)):
        frame.to_csv(out_dir / name, index=False)
    (out_dir / "baseline_meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="B1: matched random draws for a short_term_reversal run.")
    ap.add_argument("--lake")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--min-filled", type=int, default=MIN_FILLED)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--no-hash", action="store_true")
    args = ap.parse_args(argv)
    from stockbot.config.paths import lake_path
    from stockbot.data_checks.near_high_signal_count import fingerprint
    print(f"asof_view: {active_view_name()}", flush=True)
    lp = Path(args.lake) if args.lake else lake_path()
    before = fingerprint(lp, with_hash=not args.no_hash)
    meta = run_baseline(args.lake, args.run_dir, args.out_dir, draws=args.draws, min_filled=args.min_filled, seed=args.seed)
    after = fingerprint(lp, with_hash=not args.no_hash)
    meta["finsight_db"] = {"before": before, "after": after, "unchanged": before == after}
    (Path(args.out_dir) / "baseline_meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("usable_trades", "pairs_kept", "dropped_pairs", "share_dropped", "flag", "draws_total")}, indent=1))
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())
