"""stockbot/data_checks/near_high_signal_count.py - COUNTS-ONLY signal study for the near-52-week-high rule (near_52w_high). A study tool, NOT a strategy.

``py scripts/signal_count_near_high.py [--lake PATH] [--start D] [--end D] [--out-json F] [--out-md F] [--no-hash]``

The rule (fixed numbers, never varied here):
  universe  shared eligibility, no overrides (injected by the wrapper: this package may import only config and data, so it cannot import stockbot.universe);
  nearness  adjusted close[t] / max(adjusted close over the symbol's last 252 bars)   (t = as-of date; point-in-time adjusted bars from AsOfView);
  gap guard the symbol needs at least 250 bars inside the last 252 CALENDAR sessions (Nifty dates up to t). When the calendar is shorter than 252 sessions (the first
            months after 2015-11-09) the window is the whole calendar so far, and at most 2 of its sessions may be missing;
  candidate nearness >= 0.95;  rank nearness descending, ties by higher 20-session raw ADTV (AsOfView.adtv), then symbol ascending;  proposed = top 25;
  stop = 0.85 x signal-day adjusted close;  exit = fixed 40-session hold (market exit at the open of session 41) or the stop.

What it reports (all counts; every session is evaluated through ``AsOfView(conn, t)`` so no bar after ``t`` can be read):
  eligible / valid / gap-guard / candidate / proposed counts per session; data-quality counts; nearness distribution; two mechanical occupancy models of the 12-position cap
  (one without, one with the shared sector cap); runtime per session.
What it never does: compute or read a return, P&L, win rate or any price change after the signal date. The only numbers derived from prices are the signal-date nearness
(looks BACK from the as-of date) and the signal-day position size implied by the fixed 15% stop.

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
from stockbot.data.lake import open_lake
from stockbot.data.sector_map import sector_for

# ---- the rule's numbers (fixed; see the module docstring) -----------------------------------------------------------------------------------------
WINDOW = 252            # bars (and calendar sessions) of the look-back
MIN_BARS = 250          # bars required inside the window (gap guard)
THRESHOLD = 0.95
TOP_N = 25
STOP_FRACTION = 0.85
HOLD_SESSIONS = 40
TIE_ADTV_SESSIONS = 20   # tie-break: higher raw-price 20-session ADTV (the one eligibility uses), then symbol
UNADJUSTED_TYPES = ("DEMERGER", "MERGER", "RIGHTS", "OTHER")     # actions the engine does not adjust prices for (DIVIDEND is not counted: it is not a price-basis event)
FIRST_YEAR, LAST_YEAR_REPORTED = 2016, 2026
BINS = (0.95, 0.96, 0.97, 0.98, 0.99, 1.0)


def _d(v) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])


# ------------------------------------------------------------------------------------------------------------------------------------------ one session
def order_candidates(view: AsOfView, ranked: Sequence) -> list:
    """Candidates [(symbol, nearness)] in rank order: nearness descending; ties by higher raw 20-session ADTV (``view.adtv``; a name without one counts as 0), then symbol.
    ADTV is fetched only for tie groups that start inside the top TOP_N (the order beyond the cut is never used)."""
    ranked = sorted(ranked, key=lambda r: (-r[1], r[0]))
    out: list = []
    i = 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and ranked[j + 1][1] == ranked[i][1]:
            j += 1
        grp = ranked[i:j + 1]
        if len(grp) > 1 and i < TOP_N:
            adtv = {sym: (view.adtv(sym, TIE_ADTV_SESSIONS) or 0.0) for sym, _ in grp}
            grp = sorted(grp, key=lambda r: (-adtv[r[0]], r[0]))
        out.extend(grp)
        i = j + 1
    return out


def snapshot(view: AsOfView, eligible: Sequence[str]) -> dict:
    """Counts and the ranked candidate list for ONE as-of date. Reads only through ``view`` (bounded by view.as_of)."""
    t = view.as_of
    cal = view.sessions(lookback=WINDOW)
    win_start, wlen = cal[0], len(cal)
    max_missing = WINDOW - MIN_BARS              # at most 2 missing sessions of the window (also while the calendar is shorter than 252 sessions)
    out = dict(date=t, n_eligible=len(eligible), short=set(), stale=set(), gap_dropped=set(), valid=set(), ranked=[], split_in=set(), unadj_in=set(), adjust_error=set(),
               unadj_types=Counter(), exact_one=0, bin_counts=[0] * (len(BINS) - 1), cal_len=wlen)
    for sym in eligible:
        try:
            bars = view.adjusted_bars(sym, lookback=WINDOW)
        except ValueError:
            out["adjust_error"].add(sym)
            continue
        n = len(bars)
        if n < WINDOW:
            out["short"].add(sym)
            continue
        dates = list(bars.index)
        if dates[-1] != t:
            out["stale"].add(sym)
            continue
        in_win = sum(1 for d in dates if d >= win_start)
        if wlen - in_win > max_missing:
            out["gap_dropped"].add(sym)
            continue
        close = bars["close_adj"]
        c_now, c_max = float(close.iloc[-1]), float(close.max())
        if not (math.isfinite(c_now) and math.isfinite(c_max) and c_now > 0 and c_max > 0):
            out["adjust_error"].add(sym)
            continue
        try:
            cas = view.corporate_actions(sym)
            if any(dates[0] < a["ex_date"] <= t and action_factor(a) != 1.0 for a in cas):
                out["split_in"].add(sym)
        except ValueError:
            out["adjust_error"].add(sym)
            continue
        kinds = {(a["action_type"] or "").upper() for a in cas if dates[0] < a["ex_date"] <= t} & set(UNADJUSTED_TYPES)
        if kinds:
            out["unadj_in"].add(sym)
            out["unadj_types"].update(kinds)
        out["valid"].add(sym)
        near = c_now / c_max
        if near >= THRESHOLD:
            out["ranked"].append((sym, near))
            if near == 1.0:
                out["exact_one"] += 1
            else:
                for i in range(len(BINS) - 1):
                    if BINS[i] <= near < BINS[i + 1]:
                        out["bin_counts"][i] += 1
                        break
    out["ranked"] = order_candidates(view, out["ranked"])
    return out


# ----------------------------------------------------------------------------------------------------------------------------------- occupancy model
class Occupancy:
    """Mechanical occupancy of ``max_positions`` slots. Signal at close of session j; entry at the open of j+1 (= session 1 of the hold); the position is open at proposal
    time on sessions e .. e+hold-1 and its market exit executes at the open of e+hold (so ``hold`` closes are held). Engine order (fills, exits, proposals): the slot is free
    for a signal at the close of e+hold, the next entry is at the open of e+hold+1. A symbol already held is skipped.
    With ``pos_pct`` and ``sector_cap_pct`` given, a candidate whose sector value after the trade would exceed the cap is blocked (counted) and the next one considered,
    as the shared arbitration does; unmapped symbols share the UNKNOWN sector. No stops, no 15% risk cap, no costs, no gap-up cap, no cash cap, no missing-bar blocks."""

    def __init__(self, n_sessions: int, max_positions: int, hold: int = HOLD_SESSIONS, pos_pct: Optional[float] = None, sector_cap_pct: Optional[float] = None):
        self.n, self.cap, self.hold = n_sessions, max_positions, hold
        self.pos_pct, self.sector_cap = pos_pct, sector_cap_pct
        self.open: list = []
        self.entries: list = []        # (symbol, signal_idx, entry_idx, exit_idx, nearness)
        self.occupancy: list = []
        self.blocks: list = []         # sector-cap blocks per session
        self.unrealised_signals = 0

    def step(self, j: int, ranked: Sequence) -> None:
        self.open = [p for p in self.open if j < p[1]]
        self.occupancy.append(len(self.open))
        held = {p[0] for p in self.open}
        sector_n = Counter(sector_for(p[0]) for p in self.open)
        free = self.cap - len(self.open)
        blocked = 0
        for sym, score in ranked:
            if free <= 0:
                break
            if sym in held:
                continue
            if self.sector_cap is not None:
                sec = sector_for(sym)
                if (sector_n[sec] + 1) * self.pos_pct > self.sector_cap + 1e-9:
                    blocked += 1
                    continue
            if j + 1 >= self.n:
                self.unrealised_signals += 1
                free -= 1
                continue
            e = j + 1
            self.open.append((sym, e + self.hold))
            self.entries.append((sym, j, e, e + self.hold, score))
            held.add(sym)
            if self.sector_cap is not None:
                sector_n[sec] += 1
            free -= 1
        self.blocks.append(blocked)


# ------------------------------------------------------------------------------------------------------------------------------------------- the study
EVER_KEYS = ("eligible", "short", "valid", "gap_dropped", "split_in", "unadj_in", "adjust_error", "candidate", "stale")


def collect_part(conn, eligible_fn: Callable, *, start: Optional[date] = None, end: date, max_sessions: Optional[int] = None, on_session: Optional[Callable] = None,
                 progress: Optional[Callable] = None) -> dict:
    """Score every session in [start, end] (calendar = Nifty dates up to ``end``): per-session count rows and the top-TOP_N candidate list in rank order. No occupancy here, so
    contiguous date segments can be scored in separate processes and joined by ``merge_parts`` and ``assemble``. ``eligible_fn(view) -> list of symbols`` is the shared eligibility rule."""
    sess = [d for d in AsOfView(conn, end).sessions() if start is None or d >= start]
    if max_sessions:
        sess = sess[:max_sessions]
    rows: list = []
    tops: list = []
    ever: dict = {k: set() for k in EVER_KEYS}
    unadj_types: Counter = Counter()
    bin_total, exact_total = [0] * (len(BINS) - 1), 0
    t0 = time.time()
    for j, t in enumerate(sess):
        if on_session:
            on_session(t)
        view = AsOfView(conn, t)
        ta = time.perf_counter()
        elig = list(eligible_fn(view))
        tb = time.perf_counter()
        s = snapshot(view, elig)
        tc = time.perf_counter()
        tops.append([(sym, near) for sym, near in s["ranked"][:TOP_N]])
        ever["eligible"].update(elig)
        for k in ("short", "valid", "gap_dropped", "split_in", "unadj_in", "adjust_error", "stale"):
            ever[k].update(s[k])
        ever["candidate"].update(r[0] for r in s["ranked"])
        unadj_types.update(s["unadj_types"])
        exact_total += s["exact_one"]
        for i, c in enumerate(s["bin_counts"]):
            bin_total[i] += c
        rows.append(dict(date=t, eligible=s["n_eligible"], short=len(s["short"]), stale=len(s["stale"]), gap_dropped=len(s["gap_dropped"]), valid=len(s["valid"]),
                         candidates=len(s["ranked"]), proposed=len(tops[-1]), exact_one=s["exact_one"], split_in=len(s["split_in"]), unadj_in=len(s["unadj_in"]),
                         adjust_error=len(s["adjust_error"]), cal_len=s["cal_len"], t_elig=tb - ta, t_score=tc - tb))
        if progress and (j % 50 == 0 or j == len(sess) - 1):
            progress(j + 1, len(sess), t, time.time() - t0)
    return dict(sessions=sess, rows=rows, tops=tops, ever=ever, unadj_types=dict(unadj_types), bin_total=bin_total, exact_total=exact_total, seconds=time.time() - t0)


def part_to_json(part: dict) -> dict:
    """JSON-safe form of a ``collect_part`` result (dates as ISO strings, sets as sorted lists)."""
    out = dict(part)
    out["sessions"] = [d.isoformat() for d in part["sessions"]]
    out["rows"] = [{**r, "date": r["date"].isoformat()} for r in part["rows"]]
    out["ever"] = {k: sorted(v) for k, v in part["ever"].items()}
    return out


def part_from_json(d: dict) -> dict:
    out = dict(d)
    out["sessions"] = [_d(x) for x in d["sessions"]]
    out["rows"] = [{**r, "date": _d(r["date"])} for r in d["rows"]]
    out["ever"] = {k: set(v) for k, v in d["ever"].items()}
    out["tops"] = [[tuple(x) for x in t] for t in d["tops"]]
    return out


def merge_parts(parts: Sequence[dict]) -> dict:
    """Join date segments into one part (in date order). Refuses overlapping segments."""
    parts = sorted(parts, key=lambda p: p["sessions"][0])
    for a, b in zip(parts, parts[1:]):
        if not a["sessions"][-1] < b["sessions"][0]:
            raise ValueError(f"segments overlap: {a['sessions'][-1]} and {b['sessions'][0]}")
    ever = {k: set().union(*[p["ever"][k] for p in parts]) for k in EVER_KEYS}
    unadj: Counter = Counter()
    for p in parts:
        unadj.update(p["unadj_types"])
    return dict(sessions=[d for p in parts for d in p["sessions"]], rows=[r for p in parts for r in p["rows"]], tops=[t for p in parts for t in p["tops"]], ever=ever,
                unadj_types=dict(unadj), bin_total=[sum(p["bin_total"][i] for p in parts) for i in range(len(BINS) - 1)], exact_total=sum(p["exact_total"] for p in parts),
                seconds=sum(p["seconds"] for p in parts))


def assemble(part: dict, *, max_positions: int = 12, risk_pct: float = 1.0, sector_cap_pct: float = 15.0) -> dict:
    """Run the two occupancy models on a (merged) part's cached candidate lists and return the ``summarise`` input. Reads no database."""
    sess, rows, tops = part["sessions"], part["rows"], part["tops"]
    pos_pct = risk_pct / ((1.0 - STOP_FRACTION) * 100.0) * 100.0          # position value as % of equity: risk_pct / stop distance
    plain = Occupancy(len(sess), max_positions)
    capped = Occupancy(len(sess), max_positions, pos_pct=pos_pct, sector_cap_pct=sector_cap_pct)
    first_valid = first_cand = first_12 = None
    for j, (r, top) in enumerate(zip(rows, tops)):
        plain.step(j, top)
        capped.step(j, top)
        r["occupancy"], r["occupancy_capped"], r["sector_blocks"] = plain.occupancy[-1], capped.occupancy[-1], capped.blocks[-1]
        if first_valid is None and r["valid"]:
            first_valid = r["date"]
        if first_cand is None and r["candidates"]:
            first_cand = r["date"]
        if first_12 is None and r["candidates"] >= max_positions:
            first_12 = r["date"]
    mk = lambda o: [dict(symbol=e[0], signal=sess[e[1]], entry=sess[e[2]], planned_exit=(sess[e[3]] if e[3] < len(sess) else None), nearness=e[4]) for e in o.entries]  # noqa: E731
    return dict(sessions=sess, rows=rows, ever=part["ever"], unadj_types=part["unadj_types"], bin_total=part["bin_total"], exact_total=part["exact_total"], first_valid=first_valid,
                first_candidate=first_cand, first_12_candidates=first_12, calendar_first=sess[0] if sess else None, calendar_252nd_session=(sess[WINDOW - 1] if len(sess) >= WINDOW else None),
                entries=mk(plain), entries_capped=mk(capped), unrealised_signals=plain.unrealised_signals,
                params=dict(max_positions=max_positions, risk_pct=risk_pct, sector_cap_pct=sector_cap_pct, position_pct_of_equity=pos_pct), seconds=part["seconds"])


def run_study(conn, eligible_fn: Callable, *, start: Optional[date] = None, end: date, max_positions: int = 12, risk_pct: float = 1.0, sector_cap_pct: float = 15.0,
              max_sessions: Optional[int] = None, on_session: Optional[Callable] = None, progress: Optional[Callable] = None) -> dict:
    """Score and model in one process: ``collect_part`` then ``assemble``."""
    part = collect_part(conn, eligible_fn, start=start, end=end, max_sessions=max_sessions, on_session=on_session, progress=progress)
    return assemble(part, max_positions=max_positions, risk_pct=risk_pct, sector_cap_pct=sector_cap_pct)


# ---------------------------------------------------------------------------------------------------------------------------------------- summaries
def _stats(values: Sequence) -> Optional[dict]:
    if not len(values):
        return None
    a = np.asarray(values, dtype=float)
    return dict(median=float(np.median(a)), p5=float(np.percentile(a, 5)), p95=float(np.percentile(a, 95)), min=float(a.min()), max=float(a.max()), mean=float(a.mean()))


METRICS = ("eligible", "short", "gap_dropped", "valid", "candidates", "proposed", "exact_one", "split_in", "unadj_in", "adjust_error", "occupancy", "occupancy_capped",
           "sector_blocks", "invested_pct", "invested_pct_capped", "t_elig", "t_score")


def _concentration(ents: list) -> Optional[dict]:
    if not ents:
        return None
    c = Counter(e["symbol"] for e in ents)
    sec = Counter(sector_for(e["symbol"]) for e in ents)
    return dict(entries=len(ents), distinct_symbols=len(c), top_symbol=c.most_common(1)[0][0], top_symbol_share=c.most_common(1)[0][1] / len(ents),
                top10_share=sum(n for _, n in c.most_common(10)) / len(ents), sector_entries=dict(sec.most_common()),
                symbols_without_sector=sum(1 for s in c if sector_for(s) == "UNKNOWN"), entries_without_sector=sum(n for s, n in c.items() if sector_for(s) == "UNKNOWN"))


def summarise(res: dict, measured: Optional[date] = None) -> dict:
    """Per-year (2016..2026, plus the 2015 stub if present) and total tables from ``run_study`` output. Counts only."""
    measured = measured or date.today()
    rows = res["rows"]
    pp = res["params"]["position_pct_of_equity"]
    for r in rows:
        r["invested_pct"] = r["occupancy"] * pp
        r["invested_pct_capped"] = r["occupancy_capped"] * pp
    groups: dict = {}
    for r in rows:
        groups.setdefault(str(r["date"].year), []).append(r)
    groups["2016-2026"] = [r for r in rows if FIRST_YEAR <= r["date"].year <= LAST_YEAR_REPORTED]
    groups["ALL (from first session)"] = rows
    cap = res["params"]["max_positions"]

    def ents_for(key, g):
        src = res[key]
        if g.isdigit():
            return [e for e in src if str(e["entry"].year) == g]
        if g == "2016-2026":
            return [e for e in src if FIRST_YEAR <= e["entry"].year <= LAST_YEAR_REPORTED]
        return src

    out_groups: dict = {}
    for g, rs in groups.items():
        e1, e2 = ents_for("entries", g), ents_for("entries_capped", g)
        months = len(rs) / 21.0 if rs else 0.0
        occ, occc = [r["occupancy"] for r in rs], [r["occupancy_capped"] for r in rs]
        out_groups[g] = dict(sessions=len(rs), first=str(rs[0]["date"]) if rs else None, last=str(rs[-1]["date"]) if rs else None,
                             stats={m: _stats([r[m] for r in rs if r.get(m) is not None]) for m in METRICS},
                             sessions_with_any_candidate=sum(1 for r in rs if r["candidates"] > 0), sessions_with_cap_candidates=sum(1 for r in rs if r["candidates"] >= cap),
                             sessions_full=sum(1 for o in occ if o >= cap), share_sessions_full=(sum(1 for o in occ if o >= cap) / len(occ)) if occ else None,
                             sessions_full_capped=sum(1 for o in occc if o >= cap), sessions_with_sector_block=sum(1 for r in rs if r["sector_blocks"] > 0),
                             sector_blocks_total=sum(r["sector_blocks"] for r in rs),
                             entries=len(e1), entries_per_month=(len(e1) / months) if months else None, entries_capped=len(e2), entries_capped_per_month=(len(e2) / months) if months else None,
                             concentration=_concentration(e1), concentration_capped=_concentration(e2))
    ev = res["ever"]
    dist_total = sum(res["bin_total"]) + res["exact_total"]
    return dict(
        measured=str(measured), rule=dict(window=WINDOW, min_bars=MIN_BARS, threshold=THRESHOLD, top_n=TOP_N, stop_fraction=STOP_FRACTION, hold_sessions=HOLD_SESSIONS),
        params=res["params"],
        calendar=dict(first_session=str(res["calendar_first"]) if res["calendar_first"] else None, last_session=str(res["sessions"][-1]) if res["sessions"] else None,
                      n_sessions=len(res["sessions"]), calendar_252nd_session=str(res["calendar_252nd_session"]) if res["calendar_252nd_session"] else None),
        first_valid_nearness_date_with_prior_bars=str(res["first_valid"]) if res["first_valid"] else None,
        first_valid_nearness_date_calendar_only=str(res["calendar_252nd_session"]) if res["calendar_252nd_session"] else None,
        first_candidate_date=str(res["first_candidate"]) if res["first_candidate"] else None,
        first_date_with_cap_candidates=str(res["first_12_candidates"]) if res["first_12_candidates"] else None,
        groups=out_groups,
        distinct={k + "_ever": len(v) for k, v in ev.items()},
        unadjusted_action_names_by_type_session_counts=res["unadj_types"],
        nearness_distribution=dict(candidate_sessions_total=dist_total, exactly_1_00=res["exact_total"], bins={f"{BINS[i]:.2f} to <{BINS[i + 1]:.2f}": res["bin_total"][i] for i in range(len(BINS) - 1)}),
        occupancy_model=dict(entries_without_sector_cap=len(res["entries"]), entries_with_sector_cap=len(res["entries_capped"]), unrealised_signals_on_last_session=res["unrealised_signals"],
                             entries_still_open_at_end=sum(1 for e in res["entries"] if e["planned_exit"] is None)),
        entries=[dict(symbol=e["symbol"], signal=str(e["signal"]), entry=str(e["entry"]), planned_exit=str(e["planned_exit"]) if e["planned_exit"] else None, nearness=e["nearness"])
                 for e in res["entries"]],
        run_seconds=res["seconds"])


def _f(x, nd=0) -> str:
    return "-" if x is None else (f"{x:.{nd}f}" if nd else f"{x:.0f}")


def render_markdown(sm: dict) -> str:
    """Report-ready tables for items (a)-(h). Every section is stamped with the measurement date."""
    m = sm["measured"]
    order = list(sm["groups"])
    L: list = [f"# Near-52-week-high signal-count study (counts only) - measured {m}", "",
               f"Window evaluated: {sm['calendar']['first_session']} to {sm['calendar']['last_session']} ({sm['calendar']['n_sessions']} sessions). Rule numbers: {json.dumps(sm['rule'])}. "
               f"Caps: {json.dumps(sm['params'])}.", ""]
    L += [f"## (a) First date the rule can produce a valid nearness (252 bars) (measured {m})", "",
          f"- using bars before the calendar start (first session with at least one eligible name with 252 own bars that passes the gap guard): **{sm['first_valid_nearness_date_with_prior_bars']}**",
          f"- counting only calendar sessions (252nd session of the Nifty calendar, first session {sm['calendar']['first_session']}): **{sm['first_valid_nearness_date_calendar_only']}**",
          f"- first session with at least one candidate (nearness >= 0.95): {sm['first_candidate_date']}; first with at least {sm['params']['max_positions']}: {sm['first_date_with_cap_candidates']}", ""]

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

    table("(b1) Eligible names per session", "eligible")
    table("(b2) Names passing the gap guard (252 bars, >= 250 inside the window) per session", "valid")
    table("(b3) Names with nearness >= 0.95 per session", "candidates")
    table("(b4) Names proposed (top 25) per session", "proposed")
    L += [f"## (b5) Sessions with candidates (measured {m})", "", "| period | sessions | with >=1 candidate | with >= 12 candidates |", "|---|---|---|---|"]
    for g in order:
        G = sm["groups"][g]
        L.append(f"| {g} | {G['sessions']} | {G['sessions_with_any_candidate']} | {G['sessions_with_cap_candidates']} |")
    L += ["", f"## (c) Mechanical occupancy model: entries under the 12-position cap (measured {m})", "",
          "OCCUPANCY MODEL: every free slot is filled from the ranked top 25 at the next open and held exactly 40 sessions; stops, the 15% risk cap, costs, the 3% gap-up cap, "
          "the cash cap and missing next-session bars are all ignored. Stops would shorten holds and RAISE the count; the ignored blocks would LOWER it. Neither direction is bounded by this table. "
          "First column group: no sector cap. Second: with the shared 15% sector cap at the fixed position size below.", "",
          "| period | sessions | entries | per month | sessions at 12 slots | share full | entries (sector cap) | per month (sector cap) |", "|---|---|---|---|---|---|---|---|"]
    for g in order:
        G = sm["groups"][g]
        L.append(f"| {g} | {G['sessions']} | {G['entries']} | {_f(G['entries_per_month'], 2)} | {G['sessions_full']} | {_f(G['share_sessions_full'], 3)} | {G['entries_capped']} | {_f(G['entries_capped_per_month'], 2)} |")
    om = sm["occupancy_model"]
    L += ["", f"Entries without sector cap: {om['entries_without_sector_cap']}; with sector cap: {om['entries_with_sector_cap']}; entries still open at the end of the data: "
          f"{om['entries_still_open_at_end']}; signals on the last session with no next session: {om['unrealised_signals_on_last_session']}.", ""]
    L += [f"## (d) Capital use (measured {m})", "",
          f"Position size at the shared risk and the fixed 15% stop = risk % / stop distance = {sm['params']['position_pct_of_equity']:.2f}% of equity per position (signal-day close, before fill gaps, share rounding and costs).", ""]
    table("(d1) Positions open at once (no sector cap)", "occupancy")
    table("(d2) Invested share of equity, % (no sector cap)", "invested_pct")
    table("(d3) Positions open at once (with sector cap)", "occupancy_capped")
    table("(d4) Candidates blocked by the 15% sector cap per session", "sector_blocks", "A block is counted each session a ranked, not-held candidate is skipped for the sector cap while a slot is free.")
    L += [f"| period | sessions with >=1 sector block | total blocks | sessions full (cap on) |", "|---|---|---|---|"]
    for g in order:
        G = sm["groups"][g]
        L.append(f"| {g} | {G['sessions_with_sector_block']} | {G['sector_blocks_total']} | {G['sessions_full_capped']} |")
    L.append("")
    L += [f"## (e) Concentration of the occupancy model (measured {m})", "", "| period | entries | distinct symbols | largest symbol | its share | top-10 share | symbols without sector | entries without sector |", "|---|---|---|---|---|---|---|---|"]
    for g in order:
        c = sm["groups"][g]["concentration"]
        if c:
            L.append(f"| {g} | {c['entries']} | {c['distinct_symbols']} | {c['top_symbol']} | {_f(c['top_symbol_share'], 3)} | {_f(c['top10_share'], 3)} | {c['symbols_without_sector']} | {c['entries_without_sector']} |")
    allc = sm["groups"]["ALL (from first session)"]["concentration"]
    if allc:
        L += ["", "Sector split of all entries (no sector cap):", "", "| sector | entries | share |", "|---|---|---|"]
        for s, n in allc["sector_entries"].items():
            L.append(f"| {s} | {n} | {n / allc['entries']:.3f} |")
    L.append("")
    table("(f1) Eligible names with 252 bars dropped by the gap guard, per session", "gap_dropped")
    table("(f2) Eligible names with fewer than 252 bars, per session", "short")
    table("(f3) Names (passing the guard) with a split/bonus inside the 252-bar window", "split_in")
    table("(f4) Names (passing the guard) with a demerger/merger/rights/OTHER action inside the 252-bar window (the engine does not adjust these)", "unadj_in")
    D = sm["distinct"]
    L += [f"Distinct names over the whole window (measured {m}): " + "; ".join(f"{k} {v}" for k, v in D.items()) + ". "
          f"Session-name counts by unadjusted action type: {json.dumps(sm['unadjusted_action_names_by_type_session_counts'])}.", ""]
    nd = sm["nearness_distribution"]
    L += [f"## (g) Nearness among candidates (measured {m})", "", f"Candidate name-sessions in total: {nd['candidate_sessions_total']}; exactly 1.00: {nd['exactly_1_00']}.", "", "| band | name-sessions |", "|---|---|"]
    for b, n in nd["bins"].items():
        L.append(f"| {b} | {n} |")
    L.append("")
    table("(g2) Candidates sitting at exactly 1.00 per session", "exact_one")
    table("(h1) Seconds to apply the shared eligibility rule, one session", "t_elig")
    table("(h2) Seconds to score one session across the eligible universe (this tool, excluding eligibility)", "t_score")
    L.append(f"Whole run {sm['run_seconds']:.0f} s for {sm['calendar']['n_sessions']} sessions.")
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
    ap = argparse.ArgumentParser(prog="signal_count_near_high.py", description="Counts-only signal study of the near-52-week-high rule (read-only on the lake; no returns are computed).")
    ap.add_argument("--lake", help="path of finsight.db (default: STOCKBOT_DB or <repo>/finsight.db)")
    ap.add_argument("--start", help="first session to evaluate, YYYY-MM-DD (default: first calendar session)")
    ap.add_argument("--end", help="last session to evaluate, YYYY-MM-DD (default: today; the lake's own last session bounds it)")
    ap.add_argument("--max-sessions", type=int, help="evaluate only the first N sessions (smoke test)")
    ap.add_argument("--part-out", help="score the sessions only and write the per-session counts and top-25 candidate lists (the cache) as JSON; no occupancy, no report")
    ap.add_argument("--assemble", nargs="+", metavar="PART", help="no database: join cached parts (date segments), run the occupancy models and write the report")
    ap.add_argument("--out-json", help="write the summary (with the entry list) as JSON")
    ap.add_argument("--out-md", help="write the report tables as markdown (default: print to stdout)")
    ap.add_argument("--no-hash", action="store_true", help="skip the sha256 of the database file before and after (size and mtime are still compared)")
    return ap


def _write_report(sm: dict, fp_text: str, args) -> None:
    md = render_markdown(sm) + fp_text
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(sm, indent=1, default=str), encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")
    else:
        print(md)


def cli(eligible_fn: Callable, *, max_positions: int = 12, risk_pct: float = 1.0, sector_cap_pct: float = 15.0, argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.assemble:                                              # cached candidate lists only: the lake is not opened
        parts = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.assemble]
        merged = merge_parts([part_from_json(p) for p in parts])
        res = assemble(merged, max_positions=max_positions, risk_pct=risk_pct, sector_cap_pct=sector_cap_pct)
        sm = summarise(res)
        fps = [p["finsight_db"] for p in parts]
        sm["finsight_db"] = dict(parts=fps, unchanged=all(f["unchanged"] for f in fps), source="cached parts: " + ", ".join(Path(f).name for f in args.assemble))
        txt = "\n" + "\n".join(f"part {i}: before {json.dumps(f['before'])}\n        after  {json.dumps(f['after'])}\n        unchanged: {f['unchanged']}" for i, f in enumerate(fps)) + "\n"
        _write_report(sm, txt, args)
        return 0 if sm["finsight_db"]["unchanged"] else 1
    from stockbot.config.paths import lake_path
    lp = Path(args.lake) if args.lake else lake_path()
    before = fingerprint(lp, with_hash=not args.no_hash) if lp.exists() else None
    conn = open_lake(args.lake)
    progress = lambda i, n, t, s: print(f"[{i}/{n}] {t} {s:.0f}s", file=sys.stderr, flush=True)   # noqa: E731
    try:
        if args.part_out:
            part = collect_part(conn, eligible_fn, start=_d(args.start) if args.start else None, end=_d(args.end) if args.end else date.today(),
                                max_sessions=args.max_sessions, progress=progress)
        else:
            res = run_study(conn, eligible_fn, start=_d(args.start) if args.start else None, end=_d(args.end) if args.end else date.today(), max_positions=max_positions,
                            risk_pct=risk_pct, sector_cap_pct=sector_cap_pct, max_sessions=args.max_sessions, progress=progress)
    finally:
        conn.close()
    after = fingerprint(lp, with_hash=not args.no_hash)
    fp = dict(before=before, after=after, unchanged=(before == after))
    if args.part_out:
        out = part_to_json(part)
        out["finsight_db"] = fp
        Path(args.part_out).write_text(json.dumps(out, default=str), encoding="utf-8")
        return 0 if fp["unchanged"] else 1
    sm = summarise(res)
    sm["finsight_db"] = fp
    _write_report(sm, f"\nfinsight.db before: {json.dumps(before)}\nfinsight.db after:  {json.dumps(after)}\nunchanged: {before == after}\n", args)
    return 0 if before == after else 1


if __name__ == "__main__":      # pragma: no cover - the wrapper injects the shared eligibility rule; this module cannot import stockbot.universe
    print("run scripts/signal_count_near_high.py (it supplies the shared eligibility rule)", file=sys.stderr)
    sys.exit(2)
