"""COUNTS-ONLY signal study for the pullback_uptrend rule (stage 1). A study tool, NOT a strategy. Read-only on the lake; computes no return, P&L or forward price change.

  py scripts/signal_count_pullback_uptrend.py --part-out PART.json --start 2016-01-01 --end 2026-10-16 [--lake PATH] [--max-sessions N]   # score sessions, cache the counts and top-25 lists
  py scripts/signal_count_pullback_uptrend.py --assemble PART1.json PART2.json ... [--out-json F] [--out-md F]                             # no database: join parts, occupancy models, report

The rule is the strategy's own code (stockbot.strategies.pullback_uptrend): the eligible set comes from the shared eligibility function, each name goes through ``evaluate`` (the
strategy's history, SMA200 and RSI(2) code) and the ranking through ``order_signals``, so the counts cannot drift from the strategy. Every session is evaluated through
``AsOfView(conn, t)`` (no bar after t can be read). The Nifty regime of a session (close above or below the mean of its last 200 closes, 198 of 200 needed) and the Nifty's one-day
change are measured on the same view. The occupancy model reuses ``stockbot.data_checks.near_high_signal_count.Occupancy`` (12 slots, a 5-session hold, optional sector cap).
The lake is opened only through ``open_lake`` (mode=ro); ``fingerprint`` hashes the file bytes before and after.
"""
import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.adjustments import action_factor  # noqa: E402
from stockbot.data.asof import AsOfView  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.data.sector_map import sector_for  # noqa: E402
from stockbot.data_checks.near_high_signal_count import UNADJUSTED_TYPES, Occupancy, fingerprint  # noqa: E402
from stockbot.strategies.pullback_uptrend.strategy import SPEC, evaluate, order_signals  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402

P = SPEC.params
HOLD = 5                          # fixed_hold_5
SELLOFF_THRESHOLDS = (-1.0, -2.0)  # Nifty one-day change in percent; descriptive cut-offs fixed here, never varied
REGIMES = ("above", "below", "undefined")


def _d(v) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])


# ------------------------------------------------------------------------------------------------------------------------------------------ one session
def nifty_state(view: AsOfView) -> dict:
    """Nifty regime and one-day change as of ``view.as_of``: close vs the mean of its closes inside the last 200 calendar sessions (198 of 200 needed; else 'undefined')."""
    cal = view.sessions(lookback=int(P["sma_period"]))
    bars = view.index_bars(lookback=int(P["sma_period"]) + 1)
    ret = None
    if len(bars) >= 2 and bars.index[-1] == view.as_of:
        ret = float(bars["close_raw"].iloc[-1] / bars["close_raw"].iloc[-2] - 1.0) * 100.0
    if len(cal) < int(P["sma_period"]) or len(bars) == 0 or bars.index[-1] != view.as_of:
        return dict(regime="undefined", nifty_ret=ret)
    win = bars["close_raw"][[d >= cal[0] for d in bars.index]]
    if len(win) < int(P["sma_min_closes"]):
        return dict(regime="undefined", nifty_ret=ret)
    return dict(regime="above" if float(bars["close_raw"].iloc[-1]) > float(win.mean()) else "below", nifty_ret=ret)


def score_session(view: AsOfView, eligible: Sequence[str]) -> dict:
    """Funnel counts and the ranked signal list for ONE as-of date. Reads only through ``view``."""
    t = view.as_of
    cal = view.sessions(lookback=int(P["sma_period"]))
    out = dict(date=t, eligible=len(eligible), short=0, stale=0, gap=0, trend_fail=0, trend_pass=0, pullback_only=0, signals=0, sig_unadj=0, sig_split=0, sig_adjust_error=0, cal_len=len(cal))
    sigs: list = []
    first_bar: dict = {}
    calendar_ok = len(cal) >= int(P["sma_period"])
    for sym in eligible:
        bars = view.adjusted_bars(sym, lookback=int(P["min_bars"]))
        if len(bars) < int(P["min_bars"]):
            out["short"] += 1
            continue
        if bars.index[-1] != t:
            out["stale"] += 1
            continue
        if not calendar_ok:
            out["trend_fail"] += 1                              # no SMA200 exists yet: counted apart from real failures below
            continue
        win_n = sum(1 for d in bars.index if d >= cal[0])
        if win_n < int(P["sma_min_closes"]):
            out["gap"] += 1
            continue
        r = evaluate(bars, t, cal[0], P)
        if r is None:
            out["trend_fail"] += 1
            continue
        out["trend_pass"] += 1
        if r["rsi"] < float(P["rsi_max"]):
            sigs.append((sym, r["rsi"], r["close"]))
            first_bar[sym] = bars.index[0]
        else:
            out["pullback_only"] += 1
    ordered, _ = order_signals(view, sigs, int(P["top_n"]), int(P["tie_adtv_sessions"]))
    out["signals"] = len(ordered)
    for sym, _, _ in ordered:
        try:
            cas = [a for a in view.corporate_actions(sym) if a["ex_date"] > first_bar[sym]]
        except ValueError:
            out["sig_adjust_error"] += 1
            continue
        if any(action_factor(a) != 1.0 for a in cas):
            out["sig_split"] += 1
        if any((a["action_type"] or "").upper() in UNADJUSTED_TYPES for a in cas):
            out["sig_unadj"] += 1
    out["top"] = [(s, r) for s, r, _ in ordered[:int(P["top_n"])]]
    out.update(nifty_state(view))
    return out


def collect_part(conn, eligible_fn: Callable, *, start: Optional[date], end: date, max_sessions: Optional[int] = None, progress: Optional[Callable] = None) -> dict:
    sess = [d for d in AsOfView(conn, end).sessions() if start is None or d >= start]
    if max_sessions:
        sess = sess[:max_sessions]
    rows: list = []
    t0 = time.time()
    for j, t in enumerate(sess):
        view = AsOfView(conn, t)
        ta = time.perf_counter()
        elig = list(eligible_fn(view))
        tb = time.perf_counter()
        r = score_session(view, elig)
        r["t_elig"], r["t_score"] = tb - ta, time.perf_counter() - tb
        rows.append(r)
        if progress and (j % 25 == 0 or j == len(sess) - 1):
            progress(j + 1, len(sess), t, time.time() - t0)
    return dict(sessions=[d.isoformat() for d in sess], rows=[{**r, "date": r["date"].isoformat()} for r in rows], seconds=time.time() - t0)


# ------------------------------------------------------------------------------------------------------------------------------------- assemble
def _stats(values) -> Optional[dict]:
    if not len(values):
        return None
    a = np.asarray(values, dtype=float)
    return dict(median=float(np.median(a)), p5=float(np.percentile(a, 5)), p95=float(np.percentile(a, 95)), min=float(a.min()), max=float(a.max()), mean=float(a.mean()))


def merge_parts(parts: Sequence[dict]) -> dict:
    parts = sorted(parts, key=lambda p: p["sessions"][0])
    for a, b in zip(parts, parts[1:]):
        if not a["sessions"][-1] < b["sessions"][0]:
            raise ValueError(f"segments overlap: {a['sessions'][-1]} and {b['sessions'][0]}")
    return dict(sessions=[_d(x) for p in parts for x in p["sessions"]], rows=[{**r, "date": _d(r["date"])} for p in parts for r in p["rows"]], seconds=sum(p["seconds"] for p in parts))


def assemble(merged: dict, *, max_positions: int, risk_pct: float, sector_cap_pct: float) -> dict:
    """Occupancy models and every table of the stage-1 report from the cached rows. Reads no database."""
    sess, rows = merged["sessions"], merged["rows"]
    pos_pct = risk_pct / ((1.0 - float(P["stop_fraction"])) * 100.0) * 100.0           # position value as % of equity = risk % / stop distance
    plain = Occupancy(len(sess), max_positions, hold=HOLD)
    capped = Occupancy(len(sess), max_positions, hold=HOLD, pos_pct=pos_pct, sector_cap_pct=sector_cap_pct)
    for j, r in enumerate(rows):
        top = [tuple(x) for x in r["top"]]
        plain.step(j, top)
        capped.step(j, top)
        r["occupancy"], r["occupancy_capped"], r["sector_blocks"] = plain.occupancy[-1], capped.occupancy[-1], capped.blocks[-1]
    first_valid = next((r["date"] for r in rows if r["cal_len"] >= int(P["sma_period"])), None)

    def ent(o):
        return [dict(symbol=e[0], signal=sess[e[1]], entry=sess[e[2]], rsi=e[4]) for e in o.entries]
    e1, e2 = ent(plain), ent(capped)
    by_date = {r["date"]: r for r in rows}

    def months(rs):
        return len(rs) / 21.0 if rs else 0.0
    groups: dict = {}
    for r in rows:
        groups.setdefault(str(r["date"].year), []).append(r)
    valid_rows = [r for r in rows if r["cal_len"] >= int(P["sma_period"])]
    groups["from first valid session"] = valid_rows
    groups["ALL (2016-01-01 to end)"] = rows
    tables: dict = {}
    for g, rs in groups.items():
        ye = (lambda es: [e for e in es if str(e["entry"].year) == g]) if g.isdigit() else (lambda es: es)
        n1, n2 = ye(e1), ye(e2)
        if g == "from first valid session":
            n1, n2 = [e for e in e1 if e["entry"] >= first_valid], [e for e in e2 if e["entry"] >= first_valid]
        m = months(rs)
        tables[g] = dict(sessions=len(rs), stats={k: _stats([r[k] for r in rs]) for k in ("eligible", "trend_pass", "signals", "occupancy", "occupancy_capped", "sector_blocks", "t_elig", "t_score")},
                         sessions_with_signal=sum(1 for r in rs if r["signals"] > 0), sessions_over_top_n=sum(1 for r in rs if r["signals"] > int(P["top_n"])),
                         sessions_ge_cap=sum(1 for r in rs if r["signals"] >= max_positions), signal_name_sessions=sum(r["signals"] for r in rs),
                         entries=len(n1), entries_per_month=(len(n1) / m) if m else None, entries_capped=len(n2), entries_capped_per_month=(len(n2) / m) if m else None,
                         sessions_full=sum(1 for r in rs if r["occupancy"] >= max_positions), sessions_full_capped=sum(1 for r in rs if r["occupancy_capped"] >= max_positions),
                         sector_blocks_total=sum(r["sector_blocks"] for r in rs))
    # ---- Nifty regime split (all signal name-sessions, and entries of both occupancy models) -------------------------------------------------------------------------------
    regime: dict = {}
    for reg in REGIMES:
        rs = [r for r in rows if r["regime"] == reg]
        regime[reg] = dict(sessions=len(rs), share_of_sessions=len(rs) / len(rows) if rows else None, signal_name_sessions=sum(r["signals"] for r in rs),
                           sessions_with_signal=sum(1 for r in rs if r["signals"] > 0), signals_per_session=_stats([r["signals"] for r in rs]),
                           entries=sum(1 for e in e1 if by_date[e["signal"]]["regime"] == reg), entries_capped=sum(1 for e in e2 if by_date[e["signal"]]["regime"] == reg))
    tot_sig = sum(v["signal_name_sessions"] for v in regime.values())
    for v in regime.values():
        v["share_of_signal_name_sessions"] = v["signal_name_sessions"] / tot_sig if tot_sig else None
    # ---- clustering ------------------------------------------------------------------------------------------------------------------------------------------------------------
    sig = np.array([r["signals"] for r in valid_rows], dtype=float)
    order = np.sort(sig)[::-1]
    cl: dict = dict(valid_sessions=len(valid_rows), total_signal_name_sessions=float(sig.sum()))
    for pct in (5, 10, 20):
        k = max(1, int(round(len(sig) * pct / 100.0)))
        cl[f"share_of_signals_on_top_{pct}pct_sessions"] = float(order[:k].sum() / sig.sum()) if sig.sum() else None
    cl["sessions_by_signal_count"] = {"0": int((sig == 0).sum()), "1-5": int(((sig >= 1) & (sig <= 5)).sum()), "6-12": int(((sig >= 6) & (sig <= 12)).sum()),
                                      "13-25": int(((sig >= 13) & (sig <= 25)).sum()), ">25": int((sig > 25).sum())}
    cl["selloff"] = {}
    for thr in SELLOFF_THRESHOLDS:
        on = [r for r in valid_rows if r["nifty_ret"] is not None and r["nifty_ret"] <= thr]
        off = [r for r in valid_rows if r["nifty_ret"] is not None and r["nifty_ret"] > thr]
        cl["selloff"][f"nifty_day_change_le_{thr}pct"] = dict(
            sessions=len(on), share_of_sessions=len(on) / len(valid_rows) if valid_rows else None, signal_name_sessions=sum(r["signals"] for r in on),
            share_of_signal_name_sessions=(sum(r["signals"] for r in on) / sig.sum()) if sig.sum() else None, signals_per_session_on=_stats([r["signals"] for r in on]),
            signals_per_session_off=_stats([r["signals"] for r in off]), sessions_over_top_n_on=sum(1 for r in on if r["signals"] > int(P["top_n"])),
            entries=sum(1 for e in e1 if (by_date[e["signal"]]["nifty_ret"] or 0.0) <= thr and by_date[e["signal"]]["nifty_ret"] is not None),
            entries_capped=sum(1 for e in e2 if (by_date[e["signal"]]["nifty_ret"] or 0.0) <= thr and by_date[e["signal"]]["nifty_ret"] is not None))
    # ---- concentration and data quality ----------------------------------------------------------------------------------------------------------------------------------
    def conc(es):
        if not es:
            return None
        c = Counter(e["symbol"] for e in es)
        sec = Counter(sector_for(e["symbol"]) for e in es)
        return dict(entries=len(es), distinct_symbols=len(c), top_symbol=c.most_common(1)[0][0], top_symbol_share=c.most_common(1)[0][1] / len(es),
                    top10_share=sum(n for _, n in c.most_common(10)) / len(es), sector_entries=dict(sec.most_common()), entries_without_sector=sum(n for s, n in c.items() if sector_for(s) == "UNKNOWN"),
                    symbols_without_sector=sum(1 for s in c if sector_for(s) == "UNKNOWN"))
    dq = dict(signal_name_sessions=sum(r["signals"] for r in rows), with_split_or_bonus_in_window=sum(r["sig_split"] for r in rows), with_unadjusted_action_in_window=sum(r["sig_unadj"] for r in rows),
              adjust_errors=sum(r["sig_adjust_error"] for r in rows), eligible_short=_stats([r["short"] for r in valid_rows]), eligible_stale=_stats([r["stale"] for r in valid_rows]),
              eligible_gap_dropped=_stats([r["gap"] for r in valid_rows]))
    rate_sessions = len(valid_rows)
    return dict(
        params=dict(max_positions=max_positions, risk_pct=risk_pct, sector_cap_pct=sector_cap_pct, position_pct_of_equity=pos_pct, hold_sessions=HOLD, rule=dict(P)),
        calendar=dict(first_session=str(sess[0]), last_session=str(sess[-1]), n_sessions=len(sess), first_valid_session=str(first_valid) if first_valid else None,
                      sessions_without_a_200_session_calendar=len(rows) - len(valid_rows)),
        tables=tables, regime=regime, clustering=cl, data_quality=dq, concentration=conc(e1), concentration_capped=conc(e2),
        expected_trade_rate=dict(basis="entries per 21-session month from the first session with a 200-session Nifty calendar", no_sector_cap=len(e1) / (rate_sessions / 21.0) if rate_sessions else None,
                                 with_sector_cap=len([e for e in e2 if e["entry"] >= first_valid]) / (rate_sessions / 21.0) if rate_sessions and first_valid else None),
        entries=[dict(symbol=e["symbol"], signal=str(e["signal"]), entry=str(e["entry"]), rsi=e["rsi"]) for e in e1], run_seconds=merged["seconds"])


def _f(x, nd=0) -> str:
    return "-" if x is None else (f"{x:.{nd}f}" if nd else f"{x:.0f}")


def render_markdown(sm: dict, measured: str) -> str:
    cal, pr = sm["calendar"], sm["params"]
    L = [f"# pullback_uptrend: stage-1 signal counts (counts only) - measured {measured}", "",
         f"Sessions evaluated: {cal['first_session']} to {cal['last_session']} ({cal['n_sessions']} sessions). Rule: {json.dumps(pr['rule'])}. Caps: max_positions {pr['max_positions']}, "
         f"risk {pr['risk_pct']}% per trade, sector cap {pr['sector_cap_pct']}%, hold {pr['hold_sessions']} sessions, position size {pr['position_pct_of_equity']:.2f}% of equity at the 8% stop.", "",
         f"First session with a 200-session Nifty calendar (the first on which SMA200, and so a signal, can exist): **{cal['first_valid_session']}**; sessions before it: {cal['sessions_without_a_200_session_calendar']} (no signal possible, by the rule's own definition).", ""]
    order = list(sm["tables"])

    def table(title, key):
        L.extend([f"## {title}", "", "| period | sessions | median | p5 | p95 | min | max |", "|---|---|---|---|---|---|---|"])
        for g in order:
            s = sm["tables"][g]["stats"][key]
            if s:
                L.append(f"| {g} | {sm['tables'][g]['sessions']} | {_f(s['median'], 1)} | {_f(s['p5'], 1)} | {_f(s['p95'], 1)} | {_f(s['min'])} | {_f(s['max'])} |")
        L.append("")
    table("Eligible names per session (shared eligibility)", "eligible")
    table("Names above their SMA200 (history and gap guard passed) per session", "trend_pass")
    table("Signals per session (above SMA200 and RSI(2) < 10), before the top-25 cut", "signals")
    L += ["## Sessions with signals", "", "| period | sessions | with >=1 signal | with >=12 | with >25 (top-25 cut binds) | signal name-sessions |", "|---|---|---|---|---|---|"]
    for g in order:
        T = sm["tables"][g]
        L.append(f"| {g} | {T['sessions']} | {T['sessions_with_signal']} | {T['sessions_ge_cap']} | {T['sessions_over_top_n']} | {T['signal_name_sessions']} |")
    L += ["", "## Mechanical occupancy model (12 slots, 5-session hold, entry at the next open, a held symbol is skipped)", "",
          "Ignores stops (a 8% stop would end some holds early and free slots: the count would RISE), the risk cap, costs, the gap-up cap, the cash cap and missing-bar fill blocks (these LOWER it). "
          "'sector cap' = the shared 15% sector cap at the fixed position size above; unmapped symbols share one UNKNOWN sector.", "",
          "| period | sessions | entries | per month | sessions at 12 slots | entries (sector cap) | per month (sector cap) | sessions full (cap) | sector blocks |", "|---|---|---|---|---|---|---|---|---|"]
    for g in order:
        T = sm["tables"][g]
        L.append(f"| {g} | {T['sessions']} | {T['entries']} | {_f(T['entries_per_month'], 2)} | {T['sessions_full']} | {T['entries_capped']} | {_f(T['entries_capped_per_month'], 2)} | {T['sessions_full_capped']} | {T['sector_blocks_total']} |")
    et = sm["expected_trade_rate"]
    L += ["", f"**expected_trade_rate** ({et['basis']}): {_f(et['no_sector_cap'], 2)} per month without the sector cap, **{_f(et['with_sector_cap'], 2)} per month with it**.", ""]
    table("Positions open at once (no sector cap)", "occupancy")
    table("Positions open at once (with sector cap)", "occupancy_capped")
    L += ["## Signals by Nifty regime (Nifty close above or below its 200-session average; 198 of 200 closes needed; 'undefined' = fewer than 200 Nifty sessions yet)", "",
          "| Nifty vs SMA200 | sessions | share of sessions | signal name-sessions | share of signals | sessions with signal | median signals per session | entries (no cap) | entries (sector cap) |", "|---|---|---|---|---|---|---|---|---|"]
    for reg, v in sm["regime"].items():
        ss = v["signals_per_session"]
        L.append(f"| {reg} | {v['sessions']} | {_f(v['share_of_sessions'], 3)} | {v['signal_name_sessions']} | {_f(v['share_of_signal_name_sessions'], 3)} | {v['sessions_with_signal']} | {_f(ss['median'], 1) if ss else '-'} | {v['entries']} | {v['entries_capped']} |")
    c = sm["clustering"]
    L += ["", f"## Clustering of signals in sell-off days (valid sessions: {c['valid_sessions']}; signal name-sessions: {c['total_signal_name_sessions']:.0f})", "",
          "Share of all signal name-sessions on the sessions with the most signals: " + "; ".join(f"top {p}% of sessions = {_f(c[f'share_of_signals_on_top_{p}pct_sessions'], 3)}" for p in (5, 10, 20)) + ".", "",
          "Sessions by signal count: " + "; ".join(f"{k}: {v}" for k, v in c["sessions_by_signal_count"].items()) + ".", "",
          "| sell-off definition (Nifty one-day change) | sessions | share of sessions | signal name-sessions | share of signals | median signals/session (on) | median (other days) | sessions with >25 signals | entries (no cap) | entries (cap) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in c["selloff"].items():
        on, off = v["signals_per_session_on"], v["signals_per_session_off"]
        L.append(f"| {k} | {v['sessions']} | {_f(v['share_of_sessions'], 3)} | {v['signal_name_sessions']} | {_f(v['share_of_signal_name_sessions'], 3)} | {_f(on['median'], 1) if on else '-'} | {_f(off['median'], 1) if off else '-'} | {v['sessions_over_top_n_on']} | {v['entries']} | {v['entries_capped']} |")
    d = sm["data_quality"]
    L += ["", "## Data quality", "", f"Signal name-sessions {d['signal_name_sessions']}; with a split/bonus inside the 250-bar window {d['with_split_or_bonus_in_window']}; with a demerger/merger/rights/OTHER action inside it (not adjusted by the engine) "
          f"{d['with_unadjusted_action_in_window']}; adjustment errors {d['adjust_errors']}. Per session, eligible names with fewer than 250 bars: median {_f((d['eligible_short'] or {}).get('median'), 1)}; with no bar on the signal date: "
          f"median {_f((d['eligible_stale'] or {}).get('median'), 1)}; dropped by the 198-of-200 closes guard: median {_f((d['eligible_gap_dropped'] or {}).get('median'), 1)}.", ""]
    for key, title in (("concentration", "no sector cap"), ("concentration_capped", "with sector cap")):
        k = sm[key]
        if k:
            L += [f"## Concentration of the occupancy model ({title})", "", f"Entries {k['entries']}; distinct symbols {k['distinct_symbols']}; largest symbol {k['top_symbol']} ({k['top_symbol_share']:.3f}); top-10 share {k['top10_share']:.3f}; "
                  f"symbols without a sector {k['symbols_without_sector']} ({k['entries_without_sector']} entries).", ""]
    table("Seconds to apply the shared eligibility rule, one session", "t_elig")
    table("Seconds to score one session across the eligible universe", "t_score")
    L.append(f"Scoring time summed over all processes: {sm['run_seconds']:.0f} s.")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="signal_count_pullback_uptrend.py", description="Counts-only signal study of the pullback_uptrend rule (read-only on the lake; no returns are computed).")
    ap.add_argument("--lake", help="path of finsight.db (default: STOCKBOT_DB or <repo>/finsight.db)")
    ap.add_argument("--start", help="first session to evaluate, YYYY-MM-DD (default: first calendar session)")
    ap.add_argument("--end", help="last session to evaluate, YYYY-MM-DD (default: today; the lake's own last session bounds it)")
    ap.add_argument("--max-sessions", type=int, help="evaluate only the first N sessions (smoke test)")
    ap.add_argument("--part-out", help="score the sessions and write the per-session counts and top-25 lists as JSON (no occupancy, no report)")
    ap.add_argument("--assemble", nargs="+", metavar="PART", help="no database: join cached parts, run the occupancy models and write the report")
    ap.add_argument("--out-json", help="write the summary as JSON")
    ap.add_argument("--out-md", help="write the report tables as markdown (default: print)")
    ap.add_argument("--no-hash", action="store_true", help="skip the sha256 of the database file before and after (size and mtime are still compared)")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_shared_config()
    pr = cfg.portfolio_risk
    if args.assemble:
        parts = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.assemble]
        sm = assemble(merge_parts(parts), max_positions=pr.max_concurrent_positions, risk_pct=pr.max_loss_pct_per_trade, sector_cap_pct=pr.max_sector_exposure_pct)
        fps = [p["finsight_db"] for p in parts]
        sm["finsight_db"] = dict(parts=fps, unchanged=all(f["unchanged"] for f in fps))
        txt = render_markdown(sm, str(date.today())) + "\n" + "\n".join(f"part {i}: before {json.dumps(f['before'])}\n        after  {json.dumps(f['after'])}\n        unchanged: {f['unchanged']}" for i, f in enumerate(fps)) + "\n"
        if args.out_json:
            Path(args.out_json).write_text(json.dumps(sm, indent=1, default=str), encoding="utf-8")
        if args.out_md:
            Path(args.out_md).write_text(txt, encoding="utf-8")
        else:
            print(txt)
        return 0 if sm["finsight_db"]["unchanged"] else 1
    if not args.part_out:
        print("nothing to do: give --part-out (score sessions) or --assemble (report); see --help", file=sys.stderr)
        return 2
    from stockbot.config.paths import lake_path
    lp = Path(args.lake) if args.lake else lake_path()
    before = fingerprint(lp, with_hash=not args.no_hash) if lp.exists() else None
    conn = open_lake(args.lake)
    try:
        part = collect_part(conn, lambda view: eligible_symbols(view, cfg.universe), start=_d(args.start) if args.start else None, end=_d(args.end) if args.end else date.today(),
                            max_sessions=args.max_sessions, progress=lambda i, n, t, s: print(f"[{i}/{n}] {t} {s:.0f}s", file=sys.stderr, flush=True))
    finally:
        conn.close()
    after = fingerprint(lp, with_hash=not args.no_hash)
    part["finsight_db"] = dict(before=before, after=after, unchanged=(before == after))
    Path(args.part_out).write_text(json.dumps(part, default=str), encoding="utf-8")
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())
