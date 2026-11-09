"""stockbot/data_checks/momentum_signal_count.py - COUNTS-ONLY signal study for the draft relative-strength (momentum) rule. A study tool, NOT a strategy.

``py scripts/signal_count_momentum.py [--lake PATH] [--start D] [--end D] [--out-json F] [--out-md F] [--no-hash]``

The draft rule (fixed numbers, never varied here):
  universe  shared eligibility, no overrides (injected by the wrapper: this package may import only config and data, so it cannot import stockbot.universe);
  score     adjusted close[t-5] / adjusted close[t-5-126] - 1   (t = last bar of the symbol on the as-of date; "sessions" = the symbol's own last bars);
  trend     adjusted close[t] > simple average of the last 200 adjusted closes;
  rank      score descending, ties by symbol ascending;  stop = entry - 3 x ATR(14);  exit = fixed 20-session hold (market exit at the next open) or the stop.

What it reports (all counts; every session is evaluated through ``AsOfView(conn, t)`` so no bar after ``t`` can be read):
  eligible / trend / trend-and-score counts per session; data-quality counts; a mechanical occupancy simulation of the 12-position cap (no stops, no risk cap, no costs).
What it never does: compute or read a return, P&L, win rate or any price change after the signal date. The only numbers derived from prices are the signal-date score and
trend flag (both look BACK from the as-of date), and (EXTRA, flagged in the report) the signal-date 3 x ATR(14) stop distance as a share of the close.

The lake is opened only through ``stockbot.data.lake.open_lake`` (mode=ro). ``fingerprint`` hashes the FILE BYTES (the G4 check) - it does not open the database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

from stockbot.data.adjustments import action_factor
from stockbot.data.asof import AsOfView
from stockbot.data.indicators import atr, sma
from stockbot.data.lake import open_lake
from stockbot.data.sector_map import sector_for

# ---- the draft rule's numbers (fixed; see the module docstring) ----------------------------------------------------------------------------------
SCORE_LOOKBACK = 126        # sessions between the two closes of the score
SCORE_SKIP = 5              # most recent sessions skipped
SMA_WINDOW = 200            # trend average
ATR_PERIOD = 14
ATR_MULT = 3.0
HOLD_SESSIONS = 20
GAP_SESSIONS = 5            # a gap is flagged when MORE than this many calendar sessions are missing between two consecutive bars of a symbol
SCORE_BARS = SCORE_SKIP + SCORE_LOOKBACK + 1   # 132 bars: indexes t-131 .. t (the task text says "131 for the score": it is the offset; 132 bars are needed)
FIRST_YEAR, LAST_YEAR_REPORTED = 2016, 2026


def _d(v) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])


# ------------------------------------------------------------------------------------------------------------------------------------------ one session
def max_gap(bar_dates: Sequence[date], cal_pos: dict) -> int:
    """Largest number of calendar sessions missing between two consecutive bars (both must be on the calendar; bars before the calendar start are skipped)."""
    worst, prev = 0, None
    for d in bar_dates:
        p = cal_pos.get(d)
        if p is None:
            prev = None
            continue
        if prev is not None:
            worst = max(worst, p - prev - 1)
        prev = p
    return worst


def snapshot(view: AsOfView, eligible: Sequence[str], *, risk_pct: float, sector_cap_pct: float, max_positions: int = 12) -> dict:
    """Counts and the ranked candidate list for ONE as-of date. Reads only through ``view`` (bounded by view.as_of)."""
    t = view.as_of
    cal = view.sessions()
    cal_pos = {d: i for i, d in enumerate(cal)}
    out = dict(date=t, n_eligible=len(eligible), short=set(), score_only=set(), trend=set(), ranked=[], ca126=set(), ca200=set(), gap_score=set(), gap200=set(),
               anygap200=set(), adjust_error=set(), big_stop=set(), top_value_pct=None)
    value_pct: dict = {}
    for sym in eligible:
        try:
            bars = view.adjusted_bars(sym, lookback=SMA_WINDOW)
            cas = [a for a in view.corporate_actions(sym) if action_factor(a) != 1.0]
        except ValueError:                                           # an action with a missing ratio: the adjustment itself fails
            out["adjust_error"].add(sym)
            continue
        n = len(bars)
        if n < SMA_WINDOW:
            out["short"].add(sym)
            if n >= SCORE_BARS:
                out["score_only"].add(sym)
            continue
        close = bars["close_adj"]
        c_now, c_skip, c_base = float(close.iloc[-1]), float(close.iloc[-1 - SCORE_SKIP]), float(close.iloc[-SCORE_BARS])
        dates = list(bars.index)
        if not all(math.isfinite(v) and v > 0 for v in (c_now, c_skip, c_base)):
            out["adjust_error"].add(sym)
            continue
        if any(dates[-SCORE_BARS] < a["ex_date"] <= t for a in cas):
            out["ca126"].add(sym)
        if any(dates[0] < a["ex_date"] <= t for a in cas):
            out["ca200"].add(sym)
        g_score, g_200 = max_gap(dates[-SCORE_BARS:], cal_pos), max_gap(dates, cal_pos)
        if g_score > GAP_SESSIONS:
            out["gap_score"].add(sym)
        if g_200 > GAP_SESSIONS:
            out["gap200"].add(sym)
        if g_200 > 0:
            out["anygap200"].add(sym)
        if c_now > float(sma(close, SMA_WINDOW).iloc[-1]):
            out["trend"].add(sym)
            out["ranked"].append((sym, c_skip / c_base - 1.0))
            a14 = float(atr(bars["high_adj"], bars["low_adj"], close, ATR_PERIOD).iloc[-1])
            if math.isfinite(a14) and a14 > 0:                       # EXTRA: would a 1%-risk position at a 3 x ATR stop alone exceed the sector cap?
                value_pct[sym] = (risk_pct / 100.0) / (ATR_MULT * a14 / c_now) * 100.0     # position value as % of equity
                if value_pct[sym] > sector_cap_pct:
                    out["big_stop"].add(sym)
    out["ranked"].sort(key=lambda r: (-r[1], r[0]))
    if out["ranked"]:                                                # EXTRA: cash needed (% of equity) by the top-ranked candidates if each is sized at risk_pct
        out["top_value_pct"] = sum(value_pct.get(sym, 0.0) for sym, _ in out["ranked"][:max_positions])
    return out


# ----------------------------------------------------------------------------------------------------------------------------------- occupancy model
class Occupancy:
    """Mechanical occupancy of ``max_positions`` slots. Signal at close of session j; entry at the open of j+1 (= session 1 of the hold); the position is open at proposal
    time on sessions e .. e+19 and its market exit executes at the open of e+20 (hold exactly 20 sessions). ``early=0`` follows the engine order (fills, then exits, then
    proposals): the slot is free for a signal at the close of e+20 and the next entry is at the open of e+21. ``early=1`` is a naive reading in which the slot is re-used at the
    open of e+20 (a sensitivity only: the engine cannot do it, arbitration sees the position still open at the close of e+19). No stops, no 15% risk cap, no costs, no gap-up cap,
    no sector cap, no cash cap, and every name is assumed to have a next-session bar."""

    def __init__(self, n_sessions: int, max_positions: int, early: int = 0, hold: int = HOLD_SESSIONS):
        self.n, self.cap, self.early, self.hold = n_sessions, max_positions, early, hold
        self.open: list = []
        self.entries: list = []        # (symbol, signal_idx, entry_idx, exit_idx, score)
        self.occupancy: list = []      # positions open at proposal time, per session
        self.unrealised_signals = 0    # signals on the last session (no next session to fill on)

    def step(self, j: int, ranked: Sequence) -> None:
        self.open = [p for p in self.open if j < p[1] - self.early]
        self.occupancy.append(len(self.open))
        held = {p[0] for p in self.open}
        free = self.cap - len(self.open)
        for sym, score in ranked:
            if free <= 0:
                break
            if sym in held:
                continue
            if j + 1 >= self.n:
                self.unrealised_signals += 1
                free -= 1
                continue
            e = j + 1
            self.open.append((sym, e + self.hold))
            self.entries.append((sym, j, e, e + self.hold, score))
            held.add(sym)
            free -= 1


# ------------------------------------------------------------------------------------------------------------------------------------------- the study
def run_study(conn, eligible_fn: Callable, *, start: Optional[date] = None, end: date, max_positions: int = 12, risk_pct: float = 1.0, sector_cap_pct: float = 15.0,
              max_sessions: Optional[int] = None, on_session: Optional[Callable] = None, progress: Optional[Callable] = None) -> dict:
    """Evaluate every session in [start, end] (calendar = Nifty dates up to ``end``). ``eligible_fn(view) -> list of symbols`` is the shared eligibility rule."""
    sess = [d for d in AsOfView(conn, end).sessions() if start is None or d >= start]
    if max_sessions:
        sess = sess[:max_sessions]
    rows: list = []
    ever: dict = {k: set() for k in ("eligible", "short", "trend", "ca126", "ca200", "gap_score", "gap200", "anygap200", "adjust_error", "big_stop")}
    first_any = first_12 = None
    occ, occ_naive = Occupancy(len(sess), max_positions, 0), Occupancy(len(sess), max_positions, 1)
    t0 = time.time()
    for j, t in enumerate(sess):
        if on_session:
            on_session(t)
        view = AsOfView(conn, t)
        elig = list(eligible_fn(view))
        s = snapshot(view, elig, risk_pct=risk_pct, sector_cap_pct=sector_cap_pct, max_positions=max_positions)
        ranked = s["ranked"]
        occ.step(j, ranked)
        occ_naive.step(j, ranked)
        ever["eligible"].update(elig)
        for k in ("short", "trend", "ca126", "ca200", "gap_score", "gap200", "anygap200", "adjust_error", "big_stop"):
            ever[k].update(s[k])
        if first_any is None and ranked:
            first_any = t
        if first_12 is None and len(ranked) >= max_positions:
            first_12 = t
        rows.append(dict(date=t, eligible=s["n_eligible"], short=len(s["short"]), score_only=len(s["score_only"]), trend=len(s["trend"]), trend_score=len(ranked),
                         ca126=len(s["ca126"]), ca200=len(s["ca200"]), gap_score=len(s["gap_score"]), gap200=len(s["gap200"]), anygap200=len(s["anygap200"]),
                         adjust_error=len(s["adjust_error"]), big_stop=len(s["big_stop"]), top_value_pct=s["top_value_pct"], occupancy=occ.occupancy[-1], occupancy_naive=occ_naive.occupancy[-1]))
        if progress and (j % 50 == 0 or j == len(sess) - 1):
            progress(j + 1, len(sess), t, time.time() - t0)
    cal_first = sess[0] if sess else None
    return dict(sessions=sess, rows=rows, ever=ever, first_any_valid_score=first_any, first_12_candidates=first_12,
                calendar_200th_session=(sess[SMA_WINDOW - 1] if len(sess) >= SMA_WINDOW else None), calendar_first=cal_first,
                entries=[dict(symbol=e[0], signal=sess[e[1]], entry=sess[e[2]], planned_exit=(sess[e[3]] if e[3] < len(sess) else None), score=e[4]) for e in occ.entries],
                entries_naive=len(occ_naive.entries), unrealised_signals=occ.unrealised_signals, params=dict(max_positions=max_positions, risk_pct=risk_pct, sector_cap_pct=sector_cap_pct),
                seconds=time.time() - t0)


# ---------------------------------------------------------------------------------------------------------------------------------------- summaries
def _stats(values: Sequence) -> Optional[dict]:
    if not len(values):
        return None
    a = np.asarray(values, dtype=float)
    return dict(median=float(np.median(a)), p5=float(np.percentile(a, 5)), p95=float(np.percentile(a, 95)), min=float(a.min()), max=float(a.max()), mean=float(a.mean()))


METRICS = ("eligible", "short", "score_only", "trend", "trend_score", "ca126", "ca200", "gap_score", "gap200", "anygap200", "adjust_error", "big_stop", "top_value_pct", "occupancy", "occupancy_naive")


def summarise(res: dict, measured: Optional[date] = None) -> dict:
    """Per-year (2016..2026, and the 2015 stub if present) and total tables from ``run_study`` output. Counts only."""
    measured = measured or date.today()
    rows, entries = res["rows"], res["entries"]
    groups: dict = {}
    for r in rows:
        groups.setdefault(str(r["date"].year), []).append(r)
    in_range = [r for r in rows if FIRST_YEAR <= r["date"].year <= LAST_YEAR_REPORTED]
    groups["2016-2026"] = in_range
    groups["ALL (from first session)"] = rows
    cap = res["params"]["max_positions"]
    by_year_entries: dict = {}
    for e in entries:
        by_year_entries.setdefault(str(e["entry"].year), []).append(e)
    by_year_entries["2016-2026"] = [e for e in entries if FIRST_YEAR <= e["entry"].year <= LAST_YEAR_REPORTED]
    by_year_entries["ALL (from first session)"] = entries
    out_groups: dict = {}
    for g, rs in groups.items():
        ents = by_year_entries.get(g, [])
        occ = [r["occupancy"] for r in rs]
        months = len(rs) / 21.0 if rs else 0.0
        share_top = None
        if ents:
            c = Counter(e["symbol"] for e in ents)
            share_top = dict(top_symbol=c.most_common(1)[0][0], top_symbol_share=c.most_common(1)[0][1] / len(ents),
                             top10_share=sum(n for _, n in c.most_common(10)) / len(ents), distinct_symbols=len(c))
        out_groups[g] = dict(sessions=len(rs), first=str(rs[0]["date"]) if rs else None, last=str(rs[-1]["date"]) if rs else None,
                             stats={m: _stats([r[m] for r in rs if r[m] is not None]) for m in METRICS},
                             sessions_with_any_candidate=sum(1 for r in rs if r["trend_score"] > 0), sessions_with_at_least_cap_candidates=sum(1 for r in rs if r["trend_score"] >= cap),
                             sessions_full=sum(1 for o in occ if o >= cap), share_sessions_full=(sum(1 for o in occ if o >= cap) / len(occ)) if occ else None,
                             entries=len(ents), entries_per_month=(len(ents) / months) if months else None, concentration=share_top)
    allc = Counter(e["symbol"] for e in entries)
    sectors = Counter(sector_for(e["symbol"]) for e in entries)
    ever_sel = set(allc)
    no_sector = lambda s: sector_for(s) == "UNKNOWN"          # noqa: E731 - the sector map's own marker for "not in the map"
    secs = {}
    for e in entries:
        secs.setdefault(sector_for(e["symbol"]), set()).add(e["symbol"])
    return dict(
        measured=str(measured), rule=dict(score_lookback=SCORE_LOOKBACK, score_skip=SCORE_SKIP, sma_window=SMA_WINDOW, atr_period=ATR_PERIOD, atr_mult=ATR_MULT, hold_sessions=HOLD_SESSIONS,
                                           gap_sessions=GAP_SESSIONS, score_bars_needed=SCORE_BARS, sma_bars_needed=SMA_WINDOW), params=res["params"],
        calendar=dict(first_session=str(res["calendar_first"]) if res["calendar_first"] else None, last_session=str(res["sessions"][-1]) if res["sessions"] else None,
                      n_sessions=len(res["sessions"]), calendar_200th_session=str(res["calendar_200th_session"]) if res["calendar_200th_session"] else None),
        first_valid_score_date=str(res["first_any_valid_score"]) if res["first_any_valid_score"] else None,
        first_date_with_cap_candidates=str(res["first_12_candidates"]) if res["first_12_candidates"] else None,
        groups=out_groups,
        distinct=dict(eligible_ever=len(res["ever"]["eligible"]), short_history_ever=len(res["ever"]["short"]), trend_ever=len(res["ever"]["trend"]),
                      ca126_ever=len(res["ever"]["ca126"]), ca200_ever=len(res["ever"]["ca200"]), gap_score_ever=len(res["ever"]["gap_score"]),
                      gap200_ever=len(res["ever"]["gap200"]), anygap200_ever=len(res["ever"]["anygap200"]), adjust_error_ever=len(res["ever"]["adjust_error"]),
                      big_stop_ever=len(res["ever"]["big_stop"]), eligible_ever_without_sector=sum(1 for s in res["ever"]["eligible"] if no_sector(s))),
        occupancy_model=dict(entries_engine_order=len(entries), entries_naive_20_session_cycle=res["entries_naive"], unrealised_signals_on_last_session=res["unrealised_signals"],
                             entries_still_open_at_end=sum(1 for e in entries if e["planned_exit"] is None)),
        selected=dict(distinct_symbols=len(ever_sel), largest_symbol=(allc.most_common(1)[0] if allc else None), top10=allc.most_common(10),
                      symbols_without_sector=sum(1 for s in ever_sel if no_sector(s)), entries_without_sector=sum(n for s, n in allc.items() if no_sector(s)),
                      sector_entries=dict(sectors.most_common()), sector_distinct_symbols={k: len(v) for k, v in sorted(secs.items(), key=lambda kv: -len(kv[1]))}),
        entries=[dict(symbol=e["symbol"], signal=str(e["signal"]), entry=str(e["entry"]), planned_exit=str(e["planned_exit"]) if e["planned_exit"] else None, score=e["score"]) for e in entries],
        run_seconds=res["seconds"])


def _f(x, nd=0) -> str:
    return "-" if x is None else (f"{x:.{nd}f}" if nd else f"{x:.0f}")


def render_markdown(sm: dict) -> str:
    """Report-ready tables for Part 1 (a)-(h). Every table is stamped with the measurement date."""
    m = sm["measured"]
    L: list = [f"# Momentum signal-count study (counts only) - measured {m}", "",
               f"Window evaluated: {sm['calendar']['first_session']} to {sm['calendar']['last_session']} ({sm['calendar']['n_sessions']} sessions). Rule numbers: {json.dumps(sm['rule'])}. Caps: {json.dumps(sm['params'])}.", ""]
    L += [f"## (a) First date the rule can produce a valid score (measured {m})", "",
          f"- first session with at least one eligible name that has 200 bars and a finite score: **{sm['first_valid_score_date']}**",
          f"- first session with at least {sm['params']['max_positions']} such names: {sm['first_date_with_cap_candidates']}",
          f"- if only calendar sessions counted (200th session of the calendar): {sm['calendar']['calendar_200th_session']}", ""]
    order = [g for g in sm["groups"]]

    def table(title, metric, note=""):
        L.append(f"## {title} (measured {m})")
        if note:
            L.append(note)
        L.extend(["", "| period | sessions | median | p5 | p95 | min | max |", "|---|---|---|---|---|---|---|"])
        for g in order:
            s = sm["groups"][g]["stats"][metric]
            if s:
                L.append(f"| {g} | {sm['groups'][g]['sessions']} | {_f(s['median'], 1)} | {_f(s['p5'], 1)} | {_f(s['p95'], 1)} | {_f(s['min'])} | {_f(s['max'])} |")
        L.append("")

    table("(b) Eligible names per session", "eligible")
    table("(c) Names meeting the trend condition per session (200 bars needed)", "trend")
    table("(d) Names meeting the trend condition with a valid score per session", "trend_score")
    L += [f"## (d2) Sessions with candidates (measured {m})", "", "| period | sessions | with >=1 candidate | with >= cap candidates |", "|---|---|---|---|"]
    for g in order:
        G = sm["groups"][g]
        L.append(f"| {g} | {G['sessions']} | {G['sessions_with_any_candidate']} | {G['sessions_with_at_least_cap_candidates']} |")
    L += ["", f"## (e) Mechanical occupancy model: entries under the 12-position cap (measured {m})", "",
          "UPPER-BOUND OCCUPANCY MODEL: every free slot is filled from the ranked list at the next open and held exactly 20 sessions; stops, the 15% risk cap, costs, the 3% gap-up cap, "
          "the sector cap, the cash cap and missing next-session bars are all ignored. Stops would shorten holds and RAISE the count; the ignored blocks would LOWER it. "
          "Neither direction is bounded by this table.", "", "| period | sessions | entries | entries per month | sessions at full occupancy | share of sessions full |", "|---|---|---|---|---|---|"]
    for g in order:
        G = sm["groups"][g]
        L.append(f"| {g} | {G['sessions']} | {G['entries']} | {_f(G['entries_per_month'], 2)} | {G['sessions_full']} | {_f(G['share_sessions_full'], 3)} |")
    om = sm["occupancy_model"]
    L += ["", f"Total entries, engine-order timing: {om['entries_engine_order']}; naive 20-session slot cycle (sensitivity): {om['entries_naive_20_session_cycle']}; "
          f"entries still open at the end of the data: {om['entries_still_open_at_end']}; signals on the last session with no next session: {om['unrealised_signals_on_last_session']}.", ""]
    L += [f"## (f) Concentration of the occupancy model (measured {m})", "", "| period | entries | distinct symbols | largest single symbol | its share | top-10 share |", "|---|---|---|---|---|---|"]
    for g in order:
        G = sm["groups"][g]
        c = G["concentration"]
        if c:
            L.append(f"| {g} | {G['entries']} | {c['distinct_symbols']} | {c['top_symbol']} | {_f(c['top_symbol_share'], 3)} | {_f(c['top10_share'], 3)} |")
    S = sm["selected"]
    L += ["", f"Top-10 symbols overall (entries): {S['top10']}", "",
          f"Symbols selected at least once: {S['distinct_symbols']}; of them {S['symbols_without_sector']} have no sector in data/reference/sector_map.csv "
          f"({S['entries_without_sector']} entries). Eligible-ever symbols without a sector: {sm['distinct']['eligible_ever_without_sector']} of {sm['distinct']['eligible_ever']}.", "",
          "| sector | entries | distinct symbols |", "|---|---|---|"]
    for s, n in S["sector_entries"].items():
        L.append(f"| {s} | {n} | {S['sector_distinct_symbols'].get(s, 0)} |")
    L += ["", f"## (g) Distinct symbols and overlap (measured {m})", "", f"Distinct symbols ever selected: {S['distinct_symbols']}.", "",
          "| period | median positions at once | p95 | max | mean |", "|---|---|---|---|---|"]
    for g in order:
        s = sm["groups"][g]["stats"]["occupancy"]
        if s:
            L.append(f"| {g} | {_f(s['median'], 1)} | {_f(s['p95'], 1)} | {_f(s['max'])} | {_f(s['mean'], 2)} |")
    L.append("")
    table("(h1) Eligible names dropped for fewer than 200 bars, per session", "short", "Names that trade on the as-of date and pass the shared universe rules but have fewer than 200 bars (cannot be scored for trend).")
    table("(h2) Eligible names whose split/bonus adjustment falls inside the 132-bar score window", "ca126")
    table("(h3) Eligible names whose split/bonus adjustment falls inside the 200-bar window", "ca200")
    table("(h4) Eligible names with a gap of more than 5 calendar sessions inside the 200-bar window", "gap200", "EQ-only lake effect (PRE_LIVE_LIST item 11). Windows are the symbol's own last bars, so a gap makes the window span more calendar time.")
    table("(h5) Eligible names with a gap of more than 5 sessions inside the 132-bar score window", "gap_score")
    table("(h6) Eligible names with ANY missing calendar session inside the 200-bar window", "anygap200")
    D = sm["distinct"]
    L += [f"Distinct names ever, over the whole evaluated window (measured {m}): short history {D['short_history_ever']}; adjustment in score window {D['ca126_ever']}; adjustment in 200-bar window {D['ca200_ever']}; "
          f"gap >5 in score window {D['gap_score_ever']}; gap >5 in 200-bar window {D['gap200_ever']}; any gap in 200-bar window {D['anygap200_ever']}; "
          f"unusable adjustment or non-positive price {D['adjust_error_ever']}.", ""]
    table("(x) EXTRA, not in the task: candidates whose 1%-risk position at a 3 x ATR(14) stop would alone exceed the sector cap", "big_stop",
          "Uses the signal-date ATR(14) and close only (no later price). Position value = risk_pct / (3 x ATR / close); compared with the shared sector cap. Subset of the trend-and-score candidates.")
    table("(xx) EXTRA, not in the task: cash the top-ranked candidates would need, % of equity, if each is sized at the shared risk per trade with a 3 x ATR(14) stop", "top_value_pct",
          "Sum over the top-N ranked candidates (N = position cap) of risk_pct / (3 x ATR / close). Above 100 the shared cash cap (fill-time sizing is capped by cash) would shrink fills. Sessions with no candidate are left out.")
    L.append(f"Run time {sm['run_seconds']:.0f} s.")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------------------------------------------------------------------------------ G4 helper
def fingerprint(path, *, with_hash: bool = True) -> dict:
    """sha256 / size / mtime of a FILE (reads bytes; does not open it as a database). Used before and after the study: they must be identical."""
    p = Path(path)
    st = p.stat()
    h = None
    if with_hash:
        d = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                d.update(chunk)
        h = d.hexdigest()
    return dict(path=str(p), size=st.st_size, mtime_ns=st.st_mtime_ns, mtime_iso=datetime.fromtimestamp(st.st_mtime).isoformat(), sha256=h)


# --------------------------------------------------------------------------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="signal_count_momentum.py", description="Counts-only signal study of the draft momentum rule (read-only on the lake; no returns are computed).")
    ap.add_argument("--lake", help="path of finsight.db (default: STOCKBOT_DB or <repo>/finsight.db)")
    ap.add_argument("--start", help="first session to evaluate, YYYY-MM-DD (default: first calendar session)")
    ap.add_argument("--end", help="last session to evaluate, YYYY-MM-DD (default: today; the lake's own last session bounds it)")
    ap.add_argument("--max-sessions", type=int, help="evaluate only the first N sessions (smoke test)")
    ap.add_argument("--out-json", help="write the summary (with the entry list) as JSON")
    ap.add_argument("--out-md", help="write the report tables as markdown (default: print to stdout)")
    ap.add_argument("--no-hash", action="store_true", help="skip the sha256 of the database file before and after (size and mtime are still compared)")
    return ap


def cli(eligible_fn: Callable, *, max_positions: int = 12, risk_pct: float = 1.0, sector_cap_pct: float = 15.0, argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    from stockbot.config.paths import lake_path
    lp = Path(args.lake) if args.lake else lake_path()
    before = fingerprint(lp, with_hash=not args.no_hash) if lp.exists() else None
    conn = open_lake(args.lake)
    try:
        res = run_study(conn, eligible_fn, start=_d(args.start) if args.start else None, end=_d(args.end) if args.end else date.today(), max_positions=max_positions,
                        risk_pct=risk_pct, sector_cap_pct=sector_cap_pct, max_sessions=args.max_sessions,
                        progress=lambda i, n, t, s: print(f"[{i}/{n}] {t} {s:.0f}s", file=sys.stderr))
    finally:
        conn.close()
    after = fingerprint(lp, with_hash=not args.no_hash)
    sm = summarise(res)
    sm["finsight_db"] = dict(before=before, after=after, unchanged=(before == after))
    md = render_markdown(sm) + (f"\nfinsight.db before: {json.dumps(before)}\nfinsight.db after:  {json.dumps(after)}\nunchanged: {before == after}\n")
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(sm, indent=1, default=str), encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")
    else:
        print(md)
    return 0 if before == after else 1


if __name__ == "__main__":      # pragma: no cover - the wrapper injects the shared eligibility rule; this module cannot import stockbot.universe
    print("run scripts/signal_count_momentum.py (it supplies the shared eligibility rule)", file=sys.stderr)
    sys.exit(2)
