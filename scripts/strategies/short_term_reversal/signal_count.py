"""COUNTS-ONLY signal study for the short_term_reversal rule (Stage 1). A study tool, NOT a strategy. Pattern copied from stockbot/data_checks/near_high_signal_count.py.

``py scripts/signal_count_short_term_reversal.py [--lake PATH] [--start D] [--end D] [--part-out F | --assemble F...] [--out-json F] [--out-md F] [--no-hash]``

The rule is the strategy's own: this module calls ``scan`` and ``order_candidates`` from stockbot.strategies.short_term_reversal.strategy (one implementation, no copy), with the
numbers of ``SPEC.params`` (never varied here). Shared eligibility is injected by the wrapper. Every session is evaluated through ``AsOfView(conn, t)``, so no bar after ``t`` can
be read.

What it reports (counts): signals per session / year / month, sessions with more than top_n signals, the share of signals on the 10 worst market days (the Nifty's own close-to-close
move, looking back from each as-of date), sector spread, tie rate, stop fit against the shared caps, data-quality counts, and a mechanical occupancy model of the shared caps that
gives an expected_trade_rate estimate.
What it never does: compute or read a return of the strategy, P&L, win rate, or any price after the signal date. The only price-derived numbers are the signal-date ret5 (looks BACK),
the Nifty's move on each as-of date (used only to find the 10 worst market days) and the signal-day position size implied by the fixed stop.

The lake is opened only through ``stockbot.data.lake.open_lake`` (mode=ro). ``fingerprint`` hashes the FILE BYTES (the G4 check); it does not open the database.
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
from stockbot.strategies.short_term_reversal.strategy import SPEC, order_candidates, scan

P = SPEC.params
LOOKBACK, TOP_N, STOP_FRACTION, TIE_N = int(P["lookback_sessions"]), int(P["top_n"]), float(P["stop_fraction"]), int(P["tie_adtv_sessions"])
HOLD_SESSIONS = int(SPEC.exit_policy.rsplit("_", 1)[1])           # fixed_hold_5
UNADJUSTED_TYPES = ("DEMERGER", "MERGER", "RIGHTS", "OTHER")      # actions the engine does not adjust prices for
FIRST_YEAR, LAST_YEAR_REPORTED = 2016, 2026
WORST_DAYS = 10


def _d(v) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])


# ------------------------------------------------------------------------------------------------------------------------------------------ one session
def nifty_move(view: AsOfView) -> Optional[float]:
    """The Nifty's close-to-close move on the as-of date (index series, looks back one session). None on the first session of the lake."""
    b = view.index_bars(lookback=2)
    if len(b) < 2 or b.index[-1] != view.as_of:
        return None
    return float(b["close_raw"].iloc[-1] / b["close_raw"].iloc[-2] - 1.0)


def _window_events(view: AsOfView, sym: str, lo: date, hi: date) -> tuple:
    """(split_or_bonus_in_window, unadjusted_type_in_window) for corporate actions with lo < ex_date <= hi (known by the as-of date)."""
    try:
        cas = view.corporate_actions(sym)
    except ValueError:
        return False, False
    inside = [a for a in cas if lo < a["ex_date"] <= hi]
    return any(action_factor(a) != 1.0 for a in inside), bool({(a["action_type"] or "").upper() for a in inside} & set(UNADJUSTED_TYPES))


def snapshot(view: AsOfView, eligible: Sequence[str]) -> dict:
    """Counts and the ranked top list for ONE as-of date. Reads only through ``view`` (bounded by view.as_of)."""
    t = view.as_of
    res = scan(view, eligible, t, P)
    ordered, adtv_of = order_candidates(view, res["cands"], TOP_N, TIE_N)
    cal = view.sessions(lookback=LOOKBACK + 1)
    anchor = cal[0] if cal else t
    rs = [c[1] for c in ordered]
    top = ordered[:TOP_N]
    # ties: a tie group = names with exactly equal ret5
    groups = Counter(rs)
    in_tie = [c for c in top if groups[c[1]] > 1]
    straddle = len(ordered) > TOP_N and rs[TOP_N - 1] == rs[TOP_N]
    tie_groups_in_top = len({c[1] for c in in_tie})
    adtv_equal_ties = 0                                          # tie groups inside the cut where ADTV is equal too, so the symbol decides
    for r in {c[1] for c in in_tie}:
        advs = [adtv_of.get(c[0]) for c in ordered if c[1] == r]
        if len(set(advs)) < len(advs):
            adtv_equal_ties += 1
    split_in = unadj_in = 0
    sectors: Counter = Counter()
    for sym, _, _ in ordered:
        sectors[sector_for(sym)] += 1
        s, u = _window_events(view, sym, anchor, t)
        split_in += s
        unadj_in += u
    floor_unadj = sum(1 for sym in res["below_floor"] if any(_window_events(view, sym, anchor, t)))
    top_sectors = Counter(sector_for(c[0]) for c in top)
    return dict(date=t, counts=dict(res["counts"]), ordered_n=len(ordered), top=[(c[0], c[1]) for c in top], nifty=nifty_move(view), cand_sectors=dict(sectors),
                top_sector_distinct=len(top_sectors), top_sector_max=max(top_sectors.values()) if top_sectors else 0, top_unknown=top_sectors.get("UNKNOWN", 0),
                tie_names_in_top=len(in_tie), tie_groups_in_top=tie_groups_in_top, tie_straddles_cut=bool(straddle), tie_symbol_decided=adtv_equal_ties,
                split_in=split_in, unadj_in=unadj_in, floor_with_action=floor_unadj, cal_ok=len(cal) == LOOKBACK + 1)


# ----------------------------------------------------------------------------------------------------------------------------------- occupancy model
class Occupancy:
    """Mechanical occupancy of ``slots`` positions. Signal at the close of session j; entry at the open of j+1 (session 1 of the hold); the position is open at proposal time on
    sessions e .. e+hold-1 and its market exit executes at the open of e+hold, so the slot is free for a signal at the close of e+hold. A symbol already held is skipped. With
    ``pos_pct`` and ``sector_cap_pct`` given, a candidate whose sector value after the trade would exceed the cap is blocked (counted) and the next one considered, as the shared
    arbitration does; unmapped symbols share the UNKNOWN sector. No stops, no gap-down block, no costs, no gap-up cap, no cash rounding."""

    def __init__(self, n_sessions: int, slots: int, hold: int = HOLD_SESSIONS, pos_pct: Optional[float] = None, sector_cap_pct: Optional[float] = None):
        self.n, self.cap, self.hold = n_sessions, slots, hold
        self.pos_pct, self.sector_cap = pos_pct, sector_cap_pct
        self.open: list = []
        self.entries: list = []        # (symbol, signal_idx, entry_idx, exit_idx, ret5)
        self.occupancy: list = []
        self.blocks: list = []
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
COUNT_KEYS = ("eligible", "short", "stale", "no_anchor", "bad_price", "adjust_error", "valid", "below_floor", "above_cap", "signals", "no_calendar")


def collect_part(conn, eligible_fn: Callable, *, start: Optional[date] = None, end: date, max_sessions: Optional[int] = None, progress: Optional[Callable] = None) -> dict:
    """Score every session in [start, end] (calendar = Nifty dates up to ``end``): per-session rows and the top-TOP_N list. No occupancy here, so contiguous date segments can be
    scored in separate processes and joined by ``merge_parts`` and ``assemble``."""
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
        s = snapshot(view, elig)
        tc = time.perf_counter()
        rows.append({**s, "t_elig": tb - ta, "t_score": tc - tb})
        if progress and (j % 50 == 0 or j == len(sess) - 1):
            progress(j + 1, len(sess), t, time.time() - t0)
    return dict(sessions=sess, rows=rows, seconds=time.time() - t0)


def part_to_json(part: dict) -> dict:
    return dict(sessions=[d.isoformat() for d in part["sessions"]], rows=[{**r, "date": r["date"].isoformat()} for r in part["rows"]], seconds=part["seconds"])


def part_from_json(d: dict) -> dict:
    return dict(sessions=[_d(x) for x in d["sessions"]], rows=[{**r, "date": _d(r["date"]), "top": [tuple(x) for x in r["top"]]} for r in d["rows"]], seconds=d["seconds"])


def merge_parts(parts: Sequence[dict]) -> dict:
    parts = sorted(parts, key=lambda p: p["sessions"][0])
    for a, b in zip(parts, parts[1:]):
        if not a["sessions"][-1] < b["sessions"][0]:
            raise ValueError(f"segments overlap: {a['sessions'][-1]} and {b['sessions'][0]}")
    return dict(sessions=[d for p in parts for d in p["sessions"]], rows=[r for p in parts for r in p["rows"]], seconds=sum(p["seconds"] for p in parts))


def stop_fit(*, risk_pct: float, max_positions: int, max_total_risk_pct: float, sector_cap_pct: float) -> dict:
    """Arithmetic of the fixed stop against the shared caps (no prices): what one position is, and how many fit."""
    stop_dist_pct = (1.0 - STOP_FRACTION) * 100.0
    pos_pct = risk_pct / stop_dist_pct * 100.0                       # position value as % of equity at the signal-day close
    min_stop_pct = risk_pct / sector_cap_pct * 100.0                  # below this one position alone would exceed the sector cap
    return dict(stop_distance_pct=stop_dist_pct, min_stop_distance_pct=min_stop_pct, fits=stop_dist_pct >= min_stop_pct - 1e-9, position_pct_of_equity=pos_pct,
                per_sector=int(math.floor(sector_cap_pct / pos_pct + 1e-9)), cash_slots=int(math.floor(100.0 / pos_pct + 1e-9)), risk_slots=int(math.floor(max_total_risk_pct / risk_pct + 1e-9)),
                position_slots=max_positions,
                binding_slots=min(max_positions, int(math.floor(100.0 / pos_pct + 1e-9)), int(math.floor(max_total_risk_pct / risk_pct + 1e-9))))


def assemble(part: dict, *, max_positions: int = 12, risk_pct: float = 1.0, max_total_risk_pct: float = 15.0, sector_cap_pct: float = 15.0) -> dict:
    """Run the occupancy models on a (merged) part's top lists and return the ``summarise`` input. Reads no database.
    Models: ``plain`` = position-count cap only; ``sector`` = + the shared sector cap; ``shared`` = + a slot count limited by cash (100% / position size) and the total-risk cap."""
    sess, rows = part["sessions"], [dict(r) for r in part["rows"]]          # copies: the cached part is never modified
    sf = stop_fit(risk_pct=risk_pct, max_positions=max_positions, max_total_risk_pct=max_total_risk_pct, sector_cap_pct=sector_cap_pct)
    pp = sf["position_pct_of_equity"]
    models = dict(plain=Occupancy(len(sess), max_positions), sector=Occupancy(len(sess), max_positions, pos_pct=pp, sector_cap_pct=sector_cap_pct),
                  shared=Occupancy(len(sess), sf["binding_slots"], pos_pct=pp, sector_cap_pct=sector_cap_pct))
    for j, r in enumerate(rows):
        for k, m in models.items():
            m.step(j, r["top"])
            r[f"occ_{k}"] = m.occupancy[-1]
        r["sector_blocks_shared"] = models["shared"].blocks[-1]
    mk = lambda o: [dict(symbol=e[0], signal=sess[e[1]], entry=sess[e[2]], planned_exit=(sess[e[3]] if e[3] < len(sess) else None), ret5=e[4]) for e in o.entries]  # noqa: E731
    return dict(sessions=sess, rows=rows, stop_fit=sf, entries={k: mk(m) for k, m in models.items()}, unrealised={k: m.unrealised_signals for k, m in models.items()},
                params=dict(max_positions=max_positions, risk_pct=risk_pct, max_total_risk_pct=max_total_risk_pct, sector_cap_pct=sector_cap_pct, **{k: v for k, v in sf.items() if k.endswith("slots")}),
                seconds=part["seconds"])


def run_study(conn, eligible_fn: Callable, *, start: Optional[date] = None, end: date, max_sessions: Optional[int] = None, progress: Optional[Callable] = None, **caps) -> dict:
    return assemble(collect_part(conn, eligible_fn, start=start, end=end, max_sessions=max_sessions, progress=progress), **caps)


# ---------------------------------------------------------------------------------------------------------------------------------------- summaries
def _stats(values: Sequence) -> Optional[dict]:
    if not len(values):
        return None
    a = np.asarray(values, dtype=float)
    return dict(median=float(np.median(a)), p5=float(np.percentile(a, 5)), p95=float(np.percentile(a, 95)), min=float(a.min()), max=float(a.max()), mean=float(a.mean()), sum=float(a.sum()))


def worst_days(rows: Sequence, n: int = WORST_DAYS) -> dict:
    """The ``n`` sessions with the lowest Nifty close-to-close move, and the share of all signals (and of the proposed names) that fall on them, beside the share a uniform spread
    would put there (n / sessions with a Nifty move). Ties in the move are ordered by date."""
    mv = [r for r in rows if r["nifty"] is not None]
    worst = sorted(mv, key=lambda r: (r["nifty"], r["date"]))[:n]
    sig, prop = sum(r["counts"].get("signals", 0) for r in mv), sum(len(r["top"]) for r in mv)
    ws, wp = sum(r["counts"].get("signals", 0) for r in worst), sum(len(r["top"]) for r in worst)
    over = [r for r in mv if r["counts"].get("signals", 0) > TOP_N]
    return dict(n=n, sessions_with_move=len(mv), uniform_share=(n / len(mv)) if mv else None, signals_total=sig, signals_on_worst=ws, share_of_signals=(ws / sig) if sig else None,
                proposed_total=prop, proposed_on_worst=wp, share_of_proposed=(wp / prop) if prop else None, sessions_over_top_n=len(over),
                over_top_n_that_are_worst=sum(1 for r in over if r in worst),
                days=[dict(date=str(r["date"]), nifty_move=r["nifty"], signals=r["counts"].get("signals", 0), proposed=len(r["top"])) for r in worst])


def _concentration(ents: list) -> Optional[dict]:
    if not ents:
        return None
    c = Counter(e["symbol"] for e in ents)
    sec = Counter(sector_for(e["symbol"]) for e in ents)
    return dict(entries=len(ents), distinct_symbols=len(c), top_symbol=c.most_common(1)[0][0], top_symbol_share=c.most_common(1)[0][1] / len(ents),
                top10_share=sum(n for _, n in c.most_common(10)) / len(ents), sector_entries=dict(sec.most_common()), entries_without_sector=sum(n for s, n in c.items() if sector_for(s) == "UNKNOWN"))


def summarise(res: dict, measured: Optional[date] = None) -> dict:
    """Per-year (2016..2026, plus any stub) and total tables from ``assemble`` output. Counts only."""
    measured = measured or date.today()
    rows = res["rows"] = [dict(r) for r in res["rows"]]
    for r in rows:
        r["signals"] = r["counts"].get("signals", 0)
        r["proposed"] = len(r["top"])
        r["over_top_n"] = 1 if r["signals"] > TOP_N else 0
    groups: dict = {}
    for r in rows:
        groups.setdefault(str(r["date"].year), []).append(r)
    groups["2016-2026"] = [r for r in rows if FIRST_YEAR <= r["date"].year <= LAST_YEAR_REPORTED]
    groups["ALL (from first session)"] = rows

    def ents_for(model, g):
        src = res["entries"][model]
        if g.isdigit():
            return [e for e in src if str(e["entry"].year) == g]
        if g == "2016-2026":
            return [e for e in src if FIRST_YEAR <= e["entry"].year <= LAST_YEAR_REPORTED]
        return src

    out_groups: dict = {}
    for g, rs in groups.items():
        months = len(rs) / 21.0 if rs else 0.0
        occ = [r["occ_shared"] for r in rs]
        slots = res["stop_fit"]["binding_slots"]
        gd = dict(sessions=len(rs), first=str(rs[0]["date"]) if rs else None, last=str(rs[-1]["date"]) if rs else None,
                  signals_total=sum(r["signals"] for r in rs), proposed_total=sum(r["proposed"] for r in rs), sessions_with_signal=sum(1 for r in rs if r["signals"] > 0),
                  sessions_over_top_n=sum(r["over_top_n"] for r in rs), max_signals_one_day=max((r["signals"] for r in rs), default=0),
                  stats={m: _stats([r["counts"].get(m, 0) for r in rs]) for m in ("eligible", "valid", "signals", "below_floor", "short", "stale", "no_anchor")},
                  stats_proposed=_stats([r["proposed"] for r in rs]), stats_occ_shared=_stats(occ), share_sessions_full_shared=(sum(1 for o in occ if o >= slots) / len(occ)) if occ else None,
                  sector_blocks_shared_total=sum(r["sector_blocks_shared"] for r in rs), stats_t_elig=_stats([r["t_elig"] for r in rs]), stats_t_score=_stats([r["t_score"] for r in rs]))
        for model in res["entries"]:
            e = ents_for(model, g)
            gd[f"entries_{model}"] = len(e)
            gd[f"entries_{model}_per_month"] = (len(e) / months) if months else None
        gd["concentration_shared"] = _concentration(ents_for("shared", g))
        out_groups[g] = gd
    monthly: dict = {}
    for r in rows:
        k = f"{r['date'].year}-{r['date'].month:02d}"
        m = monthly.setdefault(k, dict(sessions=0, signals=0, proposed=0, sessions_over_top_n=0))
        m["sessions"] += 1
        m["signals"] += r["signals"]
        m["proposed"] += r["proposed"]
        m["sessions_over_top_n"] += r["over_top_n"]
    sec_all: Counter = Counter()
    for r in rows:
        sec_all.update(r["cand_sectors"])
    sig_total = sum(sec_all.values())
    dq: Counter = Counter()
    for r in rows:
        dq.update({k: r["counts"].get(k, 0) for k in COUNT_KEYS})
    n_sess = len(rows)
    tie = dict(proposed_total=sum(r["proposed"] for r in rows), proposed_names_in_a_tie_group=sum(r["tie_names_in_top"] for r in rows),
               sessions_with_tie_group_in_top=sum(1 for r in rows if r["tie_groups_in_top"] > 0), tie_groups_in_top=sum(r["tie_groups_in_top"] for r in rows),
               sessions_tie_straddles_cut=sum(1 for r in rows if r["tie_straddles_cut"]), tie_groups_decided_by_symbol=sum(r["tie_symbol_decided"] for r in rows),
               sessions_with_signal=sum(1 for r in rows if r["signals"] > 0))
    tie["share_of_proposed_in_a_tie_group"] = (tie["proposed_names_in_a_tie_group"] / tie["proposed_total"]) if tie["proposed_total"] else None
    tie["share_of_sessions_with_tie_in_top"] = (tie["sessions_with_tie_group_in_top"] / tie["sessions_with_signal"]) if tie["sessions_with_signal"] else None
    shared_entries = res["entries"]["shared"]
    return dict(
        measured=str(measured), rule=dict(params=dict(P), exit_policy=SPEC.exit_policy, hold_sessions=HOLD_SESSIONS), params=res["params"], stop_fit=res["stop_fit"],
        calendar=dict(first_session=str(res["sessions"][0]) if res["sessions"] else None, last_session=str(res["sessions"][-1]) if res["sessions"] else None, n_sessions=n_sess,
                      sessions_without_full_calendar=sum(1 for r in rows if not r["cal_ok"])),
        first_signal_date=next((str(r["date"]) for r in rows if r["signals"] > 0), None), groups=out_groups, monthly=monthly,
        clustering=worst_days(rows),
        sector_spread=dict(signals_total=sig_total, by_sector={s: n for s, n in sec_all.most_common()}, unknown_share=(sec_all.get("UNKNOWN", 0) / sig_total) if sig_total else None,
                           largest_sector_share=(sec_all.most_common(1)[0][1] / sig_total) if sig_total else None,
                           proposed_distinct_sectors=_stats([r["top_sector_distinct"] for r in rows if r["proposed"]]), proposed_largest_sector_names=_stats([r["top_sector_max"] for r in rows if r["proposed"]]),
                           proposed_unknown_names_total=sum(r["top_unknown"] for r in rows)),
        tie_rate=tie,
        data_quality=dict(name_session_totals=dict(dq), signals_with_split_or_bonus_in_window=sum(r["split_in"] for r in rows), signals_with_unadjusted_action_in_window=sum(r["unadj_in"] for r in rows),
                          below_floor_names_with_any_action_in_window=sum(r["floor_with_action"] for r in rows)),
        occupancy_model=dict(entries={k: len(v) for k, v in res["entries"].items()}, unrealised_signals_on_last_session=res["unrealised"],
                             entries_still_open_at_end=sum(1 for e in shared_entries if e["planned_exit"] is None)),
        entries=[dict(symbol=e["symbol"], signal=str(e["signal"]), entry=str(e["entry"]), planned_exit=str(e["planned_exit"]) if e["planned_exit"] else None, ret5=e["ret5"]) for e in shared_entries],
        run_seconds=res["seconds"])


def _f(x, nd=0) -> str:
    return "-" if x is None else (f"{x:.{nd}f}" if nd else f"{x:.0f}")


def render_markdown(sm: dict) -> str:
    """Report-ready tables. Every section is stamped with the measurement date."""
    m = sm["measured"]
    order = list(sm["groups"])
    cal = sm["calendar"]
    L: list = [f"# short_term_reversal signal-count study (counts only) - measured {m}", "",
               f"Window evaluated: {cal['first_session']} to {cal['last_session']} ({cal['n_sessions']} sessions). Rule: {json.dumps(sm['rule'])}. Caps: {json.dumps(sm['params'])}. "
               f"First session with a signal: {sm['first_signal_date']}.", ""]
    sf = sm["stop_fit"]
    L += [f"## (1) Stop fit (arithmetic, no prices) (measured {m})", "",
          f"- stop distance from the signal close: **{sf['stop_distance_pct']:.2f}%**; required minimum {sf['min_stop_distance_pct']:.2f}% (risk % / sector cap %): **{'FITS' if sf['fits'] else 'DOES NOT FIT'}**",
          f"- position at 1% risk = {sf['position_pct_of_equity']:.2f}% of equity at the signal close; positions per sector under the 15% cap: {sf['per_sector']}",
          f"- slots: position cap {sf['position_slots']}, cash ({sf['position_pct_of_equity']:.1f}% each) {sf['cash_slots']}, total-risk cap {sf['risk_slots']} -> **binding {sf['binding_slots']}**",
          "- not countable without a price after the signal: an entry open that gaps below the stop (stop at or above entry blocks the sizing) and the gap-up cap block.", ""]

    def table(title, key, note=""):
        L.append(f"## {title} (measured {m})")
        if note:
            L.append(note)
        L.extend(["", "| period | sessions | median | p5 | p95 | min | max |", "|---|---|---|---|---|---|---|"])
        for g in order:
            s = sm["groups"][g]["stats"][key] if key in sm["groups"][g]["stats"] else None
            if s:
                L.append(f"| {g} | {sm['groups'][g]['sessions']} | {_f(s['median'], 1)} | {_f(s['p5'], 1)} | {_f(s['p95'], 1)} | {_f(s['min'])} | {_f(s['max'])} |")
        L.append("")

    L += [f"## (2) Signals per year (measured {m})", "", f"A signal = ret5 inside [{P['ret_floor']}, {P['ret_cap']}] for an eligible name with usable data (before the top-{TOP_N} cut).", "",
          "| period | sessions | signals | signals/session (median) | sessions with a signal | sessions with > 25 | max in one day | proposed (top 25) |", "|---|---|---|---|---|---|---|---|"]
    for g in order:
        G = sm["groups"][g]
        L.append(f"| {g} | {G['sessions']} | {G['signals_total']} | {_f(G['stats']['signals']['median'], 1) if G['stats']['signals'] else '-'} | {G['sessions_with_signal']} | {G['sessions_over_top_n']} | {G['max_signals_one_day']} | {G['proposed_total']} |")
    L += ["", f"## (3) Signals per month (measured {m})", "", "| month | sessions | signals | proposed | sessions with > 25 |", "|---|---|---|---|---|"]
    for k, v in sm["monthly"].items():
        L.append(f"| {k} | {v['sessions']} | {v['signals']} | {v['proposed']} | {v['sessions_over_top_n']} |")
    L.append("")
    table("(4) Signals per session", "signals")
    c = sm["clustering"]
    L += [f"## (5) Clustering on the {c['n']} worst market days (measured {m})", "",
          f"Worst = lowest Nifty close-to-close move among {c['sessions_with_move']} sessions. Share of all signals on those days: **{_f(None if c['share_of_signals'] is None else 100 * c['share_of_signals'], 1)}%** "
          f"({c['signals_on_worst']} of {c['signals_total']}); a uniform spread would put {_f(None if c['uniform_share'] is None else 100 * c['uniform_share'], 2)}% there. Share of the proposed names: "
          f"{_f(None if c['share_of_proposed'] is None else 100 * c['share_of_proposed'], 1)}% ({c['proposed_on_worst']} of {c['proposed_total']}). Sessions with more than {TOP_N} signals: {c['sessions_over_top_n']}, "
          f"of which among the worst {c['n']}: {c['over_top_n_that_are_worst']}.", "", "| date | Nifty move | signals | proposed |", "|---|---|---|---|"]
    for d in c["days"]:
        L.append(f"| {d['date']} | {100 * d['nifty_move']:.2f}% | {d['signals']} | {d['proposed']} |")
    ss = sm["sector_spread"]
    L += ["", f"## (6) Sector spread (measured {m})", "", f"Signals in total {ss['signals_total']}; no sector (UNKNOWN): {_f(None if ss['unknown_share'] is None else 100 * ss['unknown_share'], 1)}%; largest sector share "
          f"{_f(None if ss['largest_sector_share'] is None else 100 * ss['largest_sector_share'], 1)}%. Proposed names per session: distinct sectors median {_f(ss['proposed_distinct_sectors']['median'], 1) if ss['proposed_distinct_sectors'] else '-'}, "
          f"most names in one sector median {_f(ss['proposed_largest_sector_names']['median'], 1) if ss['proposed_largest_sector_names'] else '-'}.", "", "| sector | signals | share |", "|---|---|---|"]
    for s, n in ss["by_sector"].items():
        L.append(f"| {s} | {n} | {n / ss['signals_total']:.3f} |")
    t = sm["tie_rate"]
    L += ["", f"## (7) Tie rate (measured {m})", "", f"Ties = exactly equal ret5 (12 decimals). Proposed names in a tie group: {t['proposed_names_in_a_tie_group']} of {t['proposed_total']} "
          f"({_f(None if t['share_of_proposed_in_a_tie_group'] is None else 100 * t['share_of_proposed_in_a_tie_group'], 2)}%); sessions with a tie group inside the top {TOP_N}: {t['sessions_with_tie_group_in_top']} of {t['sessions_with_signal']} "
          f"sessions with a signal ({_f(None if t['share_of_sessions_with_tie_in_top'] is None else 100 * t['share_of_sessions_with_tie_in_top'], 1)}%); sessions where a tie straddles the cut (decides who is proposed): "
          f"{t['sessions_tie_straddles_cut']}; tie groups where ADTV is equal too so the symbol decides: {t['tie_groups_decided_by_symbol']} of {t['tie_groups_in_top']}.", ""]
    mod = sm["occupancy_model"]
    L += [f"## (8) Expected trade rate after the shared caps (mechanical occupancy model) (measured {m})", "",
          f"OCCUPANCY MODEL: every free slot is filled from the ranked top {TOP_N} at the next open and held exactly {HOLD_SESSIONS} sessions (exit at the open of the next session); stops, "
          "costs, the 3% gap-up cap, entry gaps below the stop and missing next-session bars are ignored. Stops would shorten holds and RAISE the count; the ignored blocks would LOWER it; "
          "neither direction is bounded here. `plain`: position cap only. `sector`: + the 15% sector cap at the fixed position size. `shared`: + slots limited by cash and the total-risk cap "
          f"({sm['stop_fit']['binding_slots']} slots). Months = sessions / 21.", "",
          "| period | sessions | entries plain | per month | entries sector | per month | entries shared | per month | share of sessions at full slots (shared) | sector blocks (shared) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for g in order:
        G = sm["groups"][g]
        L.append(f"| {g} | {G['sessions']} | {G['entries_plain']} | {_f(G['entries_plain_per_month'], 2)} | {G['entries_sector']} | {_f(G['entries_sector_per_month'], 2)} | {G['entries_shared']} | "
                 f"{_f(G['entries_shared_per_month'], 2)} | {_f(G['share_sessions_full_shared'], 3)} | {G['sector_blocks_shared_total']} |")
    L += ["", f"Entries: {json.dumps(mod['entries'])}; entries still open at the end of the data (shared): {mod['entries_still_open_at_end']}; signals on the last session with no next session: "
          f"{json.dumps(mod['unrealised_signals_on_last_session'])}.", "", "Concentration of the shared model:", "", "| period | entries | distinct symbols | largest symbol | its share | top-10 share | entries without sector |", "|---|---|---|---|---|---|---|"]
    for g in order:
        k = sm["groups"][g]["concentration_shared"]
        if k:
            L.append(f"| {g} | {k['entries']} | {k['distinct_symbols']} | {k['top_symbol']} | {_f(k['top_symbol_share'], 3)} | {_f(k['top10_share'], 3)} | {k['entries_without_sector']} |")
    d = sm["data_quality"]
    L += ["", f"## (9) Data quality (measured {m})", "", f"Name-session totals: {json.dumps(d['name_session_totals'])}. Signals with a split/bonus inside the 6-bar window: {d['signals_with_split_or_bonus_in_window']}; "
          f"with a demerger/merger/rights/OTHER action there (the engine does not adjust these): {d['signals_with_unadjusted_action_in_window']}; names dropped by the -0.30 floor that have any "
          f"corporate action in the window: {d['below_floor_names_with_any_action_in_window']} of {d['name_session_totals'].get('below_floor', 0)}. Sessions without a full 6-session calendar: "
          f"{sm['calendar']['sessions_without_full_calendar']}.", ""]
    table("(9a) Eligible names per session", "eligible")
    table("(9b) Names with a usable ret5 per session", "valid")
    table("(9c) Names below the -0.30 floor per session (the artifact guard)", "below_floor")
    table("(9d) Names with fewer than 10 bars per session", "short")
    table("(9e) Names with no bar on the 5-session-back anchor date per session", "no_anchor")
    L.append(f"Whole run {sm['run_seconds']:.0f} s for {sm['calendar']['n_sessions']} sessions (sum over parts).")
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
    ap = argparse.ArgumentParser(prog="signal_count_short_term_reversal.py", description="Counts-only signal study of the short_term_reversal rule (read-only on the lake; no returns are computed).")
    ap.add_argument("--lake", help="path of finsight.db (default: STOCKBOT_DB or <repo>/finsight.db)")
    ap.add_argument("--start", help="first session to evaluate, YYYY-MM-DD (default: first calendar session)")
    ap.add_argument("--end", help="last session to evaluate, YYYY-MM-DD (default: today; the lake's own last session bounds it)")
    ap.add_argument("--max-sessions", type=int, help="evaluate only the first N sessions (smoke test)")
    ap.add_argument("--part-out", help="score the sessions only and write the per-session rows (the cache) as JSON; no occupancy, no report")
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


def cli(eligible_fn: Callable, *, max_positions: int = 12, risk_pct: float = 1.0, max_total_risk_pct: float = 15.0, sector_cap_pct: float = 15.0, argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    caps = dict(max_positions=max_positions, risk_pct=risk_pct, max_total_risk_pct=max_total_risk_pct, sector_cap_pct=sector_cap_pct)
    if args.assemble:                                              # cached parts only: the lake is not opened
        parts = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.assemble]
        res = assemble(merge_parts([part_from_json(p) for p in parts]), **caps)
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
    end = _d(args.end) if args.end else date.today()
    try:
        if args.part_out:
            part = collect_part(conn, eligible_fn, start=_d(args.start) if args.start else None, end=end, max_sessions=args.max_sessions, progress=progress)
        else:
            res = run_study(conn, eligible_fn, start=_d(args.start) if args.start else None, end=end, max_sessions=args.max_sessions, progress=progress, **caps)
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


if __name__ == "__main__":      # pragma: no cover - the wrapper injects the shared eligibility rule
    print("run scripts/signal_count_short_term_reversal.py (it supplies the shared eligibility rule)", file=sys.stderr)
    sys.exit(2)
