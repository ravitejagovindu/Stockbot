"""Descriptive statistics of the market switch on the real Nifty / VIX series (Part B1 and B2 of the market-switch comparison; NOT a registered trial, writes no ledger row).

  py scripts/market_switch_stats.py --out DIR [--start 2016-01-01] [--end 2026-10-16] [--lake PATH]

B1: sessions ACTIVE / CLEAR, share of time ACTIVE, number of flips, every ACTIVE period (start, end, length, reason at activation). The overlay is evaluated through the as-of view
from the window start with a fresh state (exactly as a backtest of the window starts), so the states are the ones an engine run sees.
B2 (index only, no engine): Nifty buy-and-hold against "Nifty while CLEAR, cash at 6.5% a year while ACTIVE". The state decided on close T is executed at the OPEN of T+1; every execution
pays 0.22% (a full exit-and-re-entry cycle = 0.44% round trip). Both lines start fully invested at the first session open of the period without an entry cost. Cash earns 6.5% a year
(simple compounding by calendar days) for intervals fully spent in cash; the intra-day part of a switch day earns no interest. Close-to-close marks; max drawdown on closes.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.config.paths import lake_path  # noqa: E402
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import AsOfView, NIFTY, VIX, active_view_name  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.overlays import resolve_default_overlays  # noqa: E402

COST_ONE_SIDE = 0.0022
CASH_RATE = 0.065


def switch_states(conn, start: date, end: date, cfg):
    ms = resolve_default_overlays(cfg)["market_switch_v1"]
    end_view = AsOfView(conn, end)
    days = [d for d in end_view.sessions() if start <= d <= end]
    st, rows = {}, []
    for d in days:
        sig, st = ms.evaluate(AsOfView(conn, d), st)
        rows.append({"date": d, "state": sig["state"], "reason": sig["reason"], "count": sig["reentry_count"], "nifty": sig["nifty_close"], "vix": sig["vix_close"]})
    return pd.DataFrame(rows)


def periods(df: pd.DataFrame) -> list:
    out, cur = [], None
    for r in df.itertuples():
        if r.state == "ACTIVE" and cur is None:
            cur = {"start": r.date, "reason": r.reason, "n": 0}
        if cur is not None:
            cur["n"] += r.state == "ACTIVE"
            if r.state == "CLEAR":
                out.append({**cur, "end": prev})            # last ACTIVE session
                cur = None
        prev = r.date
    if cur is not None:
        out.append({**cur, "end": prev, "open_at_window_end": True})
    return out


def run_index(df: pd.DataFrame, bars: pd.DataFrame, since: date, until: date, switched: bool) -> pd.Series:
    """Equity per session close (100 at the start) of the index held always (switched=False) or only while CLEAR (decision on close T, executed at the open of T+1)."""
    b = bars.loc[since:until]
    st = df.set_index("date")["state"]
    invested, eq, prev_close, prev_date = True, 100.0, None, None
    out = {}
    first = True
    for d, row in b.iterrows():
        if first:
            first = False
            eq *= row["close_raw"] / row["open_raw"]                       # fully invested from the first open (state at that open: CLEAR by construction of the window start)
            out[d] = eq
            prev_close, prev_date = row["close_raw"], d
            continue
        want = True if not switched else st[prev_date] == "CLEAR"       # state decided on the previous close
        gap_days = (d - prev_date).days
        if invested:
            eq *= row["open_raw"] / prev_close
        elif not want:
            eq *= (1 + CASH_RATE) ** (gap_days / 365.0)
        if switched and want != invested:
            eq *= 1 - COST_ONE_SIDE
            invested = want
        if invested:
            eq *= row["close_raw"] / row["open_raw"]
        out[d] = eq
        prev_close, prev_date = row["close_raw"], d
    return pd.Series(out)


def metrics(eq: pd.Series) -> dict:
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    dd = (eq / eq.cummax() - 1).min() * 100
    yr = {}
    prev = 100.0
    for y in sorted({d.year for d in eq.index}):
        last = eq[[d for d in eq.index if d.year == y]].iloc[-1]
        yr[y] = (last / prev - 1) * 100
        prev = last
    return {"cagr_pct": ((eq.iloc[-1] / 100.0) ** (1 / years) - 1) * 100, "max_drawdown_pct": -dd, "worst_calendar_year_pct": min(yr.values()), "worst_year": min(yr, key=yr.get),
            "calendar_years_pct": yr, "total_return_pct": (eq.iloc[-1] / 100 - 1) * 100, "years": years, "first": eq.index[0].isoformat(), "last": eq.index[-1].isoformat()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lake")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    cfg = load_shared_config()
    conn = open_lake(args.lake or lake_path())
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    df = switch_states(conn, start, end, cfg)
    bars = AsOfView(conn, end).index_bars(NIFTY, None)
    n_active = int((df["state"] == "ACTIVE").sum())
    per = periods(df)
    flips = int((df["state"] != df["state"].shift()).sum() - 1)
    b1 = {"asof_view": active_view_name(), "window": [start.isoformat(), end.isoformat()], "sessions": len(df), "active": n_active, "clear": len(df) - n_active, "share_active_pct": 100 * n_active / len(df),
          "flips_total": flips, "activations": sum(1 for _ in per), "periods": [{"start": p["start"].isoformat(), "end": p["end"].isoformat(), "sessions": int(p["n"]),
                                                                              "calendar_days": (p["end"] - p["start"]).days + 1, "reason_at_activation": p["reason"],
                                                                              "open_at_window_end": bool(p.get("open_at_window_end"))} for p in per]}
    reasons: dict = {}
    for p in per:
        reasons[p["reason"]] = reasons.get(p["reason"], 0) + 1
    b1["activation_reasons"] = reasons
    b2 = {}
    for name, (a, z) in {"full": (start, end), "2016-2019": (date(2016, 1, 1), date(2019, 12, 31)), "2020-2026": (date(2020, 1, 1), end)}.items():
        sub = df[(df["date"] >= a) & (df["date"] <= z)].reset_index(drop=True)
        # the state in force at the first open of a sub-period is the one decided on the previous close; the sub-period starts invested at its first open (no entry cost) in both lines
        bh, sw = run_index(df, bars, a, z, False), run_index(df, bars, a, z, True)
        b2[name] = {"buy_and_hold": metrics(bh), "switch_with_cash": metrics(sw), "sessions": len(sub), "share_active_pct": 100 * (sub["state"] == "ACTIVE").mean(),
                    "state_flips": int((sub["state"] != sub["state"].shift()).sum()) - 1}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df.assign(date=df["date"].map(lambda d: d.isoformat())).to_csv(out / "switch_states.csv", index=False)
    (out / "b1_switch_statistics.json").write_text(json.dumps(b1, indent=1), encoding="utf-8")
    (out / "b2_index_only.json").write_text(json.dumps(b2, indent=1, default=float), encoding="utf-8")
    print(json.dumps({"b1": {k: v for k, v in b1.items() if k != "periods"}, "b2": {k: {a: {m: v[m] for m in ("cagr_pct", "max_drawdown_pct", "worst_calendar_year_pct", "worst_year")}
                                                                                for a, v in d.items() if a in ("buy_and_hold", "switch_with_cash")} for k, d in b2.items()}}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
