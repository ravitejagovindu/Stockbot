"""Proofs and effect numbers for the stale-positions work (read-only on the lake; no engine run of any strategy; nothing stored is changed).

  py -3 scripts/stale_positions_proofs.py diff   --out FILE   # A3 (ii): switch on vs off, every unlinked symbol, >= 400 real sessions (in-memory view)
  py -3 scripts/stale_positions_proofs.py pairs  --out FILE   # A3 (iii) + (iv): every linked pair, continuity, once-only actions, listing age, SQL view = memory view
  py -3 scripts/stale_positions_proofs.py effect --out FILE   # section E: stored trades that the no-bars rule would have closed; eligibility changes per year with linking on

All three use finsight.db through ``open_lake`` (read-only). ``STOCKBOT_DB`` selects the file.
"""
import argparse
import json
import os
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stockbot.config.paths import lake_path  # noqa: E402
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data import symbol_links  # noqa: E402
from stockbot.data.asof import AsOfView, _fund_symbols  # noqa: E402
from stockbot.data.asof_memory import MemoryAsOfView  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.universe.eligibility import CRORE, eligible_symbols  # noqa: E402

CFG = load_shared_config()
STORED = {"near_52w_high 4B": "docs/strategies/near_52w_high/results_4B/run/trades.json",
          "pullback_uptrend run1": "docs/strategies/pullback_uptrend/results_run1/run/trades.json",
          "short_term_reversal run1": "docs/strategies/short_term_reversal/results_run1/run/trades.json",
          "riskadj_momentum run1": "docs/strategies/riskadj_momentum/results_run1/run/trades.json"}


def links_table() -> pd.DataFrame:
    return pd.read_csv(ROOT / "data/reference/symbol_links.csv")


def sql_view(conn, d):
    v = object.__new__(AsOfView)
    v.__init__(conn, d)
    return v


def frames_equal(a, b) -> bool:
    return a.equals(b)


# ------------------------------------------------------------------------------------------------------------------------------ (ii) diff harness
def diff_harness(conn, n_sessions=450, sample=250, seed=20261115) -> dict:
    L = links_table()
    linked = set(L.old_symbol) | set(L.new_symbol)
    sessions = [d for d in AsOfView(conn, date(2026, 10, 16)).sessions() if d >= date(2016, 1, 1)]
    rng = random.Random(seed)
    pick = sorted(rng.sample(sessions, n_sessions))
    out = {"sessions": len(pick), "first": pick[0].isoformat(), "last": pick[-1].isoformat(), "per_session_symbol_sample": sample, "linked_symbols": len(linked), "compared": Counter(), "differences": []}
    for d in pick:
        with symbol_links.override(enabled=False):
            off = MemoryAsOfView(conn, d)
            trade_off, elig_off = off.symbols_trading(), eligible_symbols(off, CFG.universe)
            syms = sorted(s for s in trade_off if s not in linked)
            take = rng.sample(syms, min(sample, len(syms)))
            ref = {s: (off.raw_bars(s, lookback=60), off.adjusted_bars(s, lookback=60), off.corporate_actions(s), off.symbol_info(s), off.adtv(s)) for s in take}
            sess_off = off.sessions(lookback=5)
        with symbol_links.override(enabled=True):
            on = MemoryAsOfView(conn, d)
            trade_on, elig_on = on.symbols_trading(), eligible_symbols(on, CFG.universe)
            if [s for s in trade_off if s not in linked] != [s for s in trade_on if s not in linked]:
                out["differences"].append({"date": d.isoformat(), "what": "symbols_trading (unlinked part)"})
            if [s for s in elig_off if s not in linked] != [s for s in elig_on if s not in linked]:
                out["differences"].append({"date": d.isoformat(), "what": "eligible (unlinked part)"})
            if sess_off != on.sessions(lookback=5):
                out["differences"].append({"date": d.isoformat(), "what": "sessions"})
            for s in take:
                got = (on.raw_bars(s, lookback=60), on.adjusted_bars(s, lookback=60), on.corporate_actions(s), on.symbol_info(s), on.adtv(s))
                same = frames_equal(ref[s][0], got[0]) and frames_equal(ref[s][1], got[1]) and ref[s][2] == got[2] and ref[s][3] == got[3] and ref[s][4] == got[4]
                out["compared"]["symbol_sessions"] += 1
                if not same:
                    out["differences"].append({"date": d.isoformat(), "symbol": s, "what": "bars/adjusted/actions/info/adtv"})
            out["compared"]["eligible_unlinked_checked"] += len([s for s in elig_on if s not in linked])
    out["compared"] = dict(out["compared"])
    out["differences_total"] = len(out["differences"])
    out["identical"] = not out["differences"]
    return out


# ------------------------------------------------------------------------------------------------------------------------------ (iii)+(iv) the pairs
def pair_proofs(conn) -> dict:
    L = links_table()
    last = date(2026, 10, 16)
    rows, problems = [], []
    memo = MemoryAsOfView(conn, last)
    with symbol_links.override(enabled=True):
        links = symbol_links.active()
        for p in L.itertuples():
            chain = links.members(p.new_symbol)
            latest = links.resolve(p.old_symbol)
            old_last, new_first = date.fromisoformat(p.old_last_bar), date.fromisoformat(p.new_first_bar)
            v = MemoryAsOfView(conn, last)
            raw = v.raw_bars(latest, lookback=None)
            phys = {s: v._raw_bars_physical(s, None) for s in chain}
            expect_n = sum(len(f) for f in phys.values())
            no_dup = bool(raw.index.is_unique) and len(raw) == expect_n and raw.index.is_monotonic_increasing
            adj = v.adjusted_bars(latest, lookback=None)["close_adj"]
            ratio = float(adj.loc[new_first] / adj.loc[old_last])
            ses = v.sessions()
            missing_between = [d for d in ses if old_last < d < new_first]
            acts = v.corporate_actions(latest)
            keys = [(a["ex_date"], a["action_type"], a["ratio_numerator"], a["ratio_denominator"]) for a in acts]
            once = len(keys) == len(set(keys))
            boundary_actions = [(a["ex_date"].isoformat(), a["action_type"], a["ratio_numerator"], a["ratio_denominator"]) for a in acts if old_last <= a["ex_date"] <= new_first and a["action_type"] in ("SPLIT", "BONUS")]
            info_on = v.symbol_info(latest)
            with symbol_links.override(enabled=False):
                info_new_alone = MemoryAsOfView(conn, last).symbol_info(p.new_symbol)
            first_old = v._first_and_count_physical(chain[0])[0]
            age_ok = info_on.first_date == first_old and info_on.listing_age_days >= info_new_alone.listing_age_days
            # SQL view = memory view for this stock at three dates
            sqlsame = True
            for d in (old_last, new_first, last):
                a, b = sql_view(conn, d), MemoryAsOfView(conn, d)
                sqlsame = sqlsame and a.raw_bars(latest, lookback=None).equals(b.raw_bars(latest, lookback=None)) and a.adjusted_bars(latest, lookback=80).equals(b.adjusted_bars(latest, lookback=80)) \
                    and a.corporate_actions(latest) == b.corporate_actions(latest) and a.symbol_info(latest) == b.symbol_info(latest) and a.adtv(latest) == b.adtv(latest)
            row = {"old": p.old_symbol, "new": p.new_symbol, "latest": latest, "old_last": p.old_last_bar, "new_first": p.new_first_bar, "adjusted_close_ratio_across_boundary": round(ratio, 6),
                   "bars_combined": len(raw), "bars_old_plus_new": expect_n, "no_duplicate_or_dropped_session": no_dup, "sessions_between_in_engine_calendar": len(missing_between),
                   "corporate_actions_unique": once, "boundary_split_bonus_rows": boundary_actions, "listing_age_days": info_on.listing_age_days, "first_bar": str(info_on.first_date),
                   "listing_age_carries_over": bool(age_ok), "sql_equals_memory": bool(sqlsame)}
            rows.append(row)
            if not (no_dup and once and age_ok and sqlsame and 0.5 < ratio < 2.0):
                problems.append(row)
    # the named test: PHILIPCARB / PCBL, split ex 2018-04-19
    ph = next(r for r in rows if r["old"] == "PHILIPCARB")
    return {"pairs": len(rows), "rows": rows, "problems": problems, "all_ok": not problems, "philipcarb_pcbl": ph}


# ------------------------------------------------------------------------------------------------------------------------------ E
def eligible_one(v, sym, funds) -> bool:
    """The shared eligibility rule for ONE symbol (copy of stockbot.universe.eligibility.eligible_symbols' per-symbol test; verified equal to it on sample sessions)."""
    info = v.symbol_info(sym)
    if info.is_fund_or_etf or info.listing_age_days is None or info.listing_age_days < CFG.universe.min_listing_age_trading_days:
        return False
    adtv = v.adtv(sym, 20)
    return adtv is not None and adtv / CRORE > CFG.universe.min_adtv_cr


def effect(conn) -> dict:
    last = date(2026, 10, 16)
    ses_all = AsOfView(conn, last).sessions()
    ses = [d for d in ses_all if d >= date(2016, 1, 1)]
    L = links_table()
    out = {"stored_runs": {}, "eligibility": {}}
    # ---- stored trades the rule would have closed
    with symbol_links.override(enabled=True):
        links = symbol_links.active()
        v_end = MemoryAsOfView(conn, last)
        n = CFG.engine.stale_exit_sessions
        sidx = {d: i for i, d in enumerate(ses_all)}
        for label, rel in STORED.items():
            trades = json.loads((ROOT / rel).read_text(encoding="utf-8"))
            hit, linked_trades = [], []
            for t in trades:
                sym = t["symbol"]
                latest = links.resolve(sym)
                is_linked = sym in links.linked_symbols()
                if is_linked:
                    linked_trades.append({"position_id": t["position_id"], "symbol": sym, "latest": latest, "entry": t["entry_date"], "exit": t["exit_date"], "reason": t["exit_reason"]})
                e, x = date.fromisoformat(t["entry_date"]), date.fromisoformat(t["exit_date"])
                bars_ = v_end.raw_bars(latest, lookback=None, start=e)
                dates = [d for d in bars_.index if d >= e]
                have = set(dates)
                run = 0
                closed_on = None
                for d in ses_all[sidx[e]:]:
                    if d > x:
                        break
                    if d in have:
                        run = 0
                    elif d > e:
                        run += 1
                        if run == n:
                            closed_on = d
                            break
                if closed_on is not None:
                    last_bar = max(d for d in dates if d < closed_on) if [d for d in dates if d < closed_on] else e
                    hit.append({"position_id": t["position_id"], "symbol": sym, "latest_symbol": latest, "linked": is_linked, "entry": t["entry_date"], "stored_exit": t["exit_date"], "stored_reason": t["exit_reason"],
                                "last_bar": last_bar.isoformat(), "closed_by_rule_on": closed_on.isoformat(), "sessions_earlier_than_stored_exit": sidx[x] - sidx[closed_on]})
            out["stored_runs"][label] = {"trades": len(trades), "closed_by_rule": len(hit), "of_which_stored_exit_END_OF_WINDOW": sum(1 for h in hit if h["stored_reason"] in ("END_OF_WINDOW", "END_OF_WINDOW_COUNTED")),
                                         "of_which_symbol_linked": sum(1 for h in hit if h["linked"]), "trades_involving_a_linked_symbol": len(linked_trades), "list": hit, "linked_trades": linked_trades}
    # ---- eligibility changes with linking on, per year (linked stocks only; every other symbol is unchanged, see the diff harness)
    funds = _fund_symbols()
    chains = {}
    with symbol_links.override(enabled=True):
        links = symbol_links.active()
        for s in links.linked_symbols():
            chains[links.resolve(s)] = links.members(s)
    per_year: dict = {}
    sample_check = {"sessions_checked": 0, "mismatches": 0}
    check_days = set(random.Random(7).sample(ses, 25))
    for d in ses:
        with symbol_links.override(enabled=False):
            off = MemoryAsOfView(conn, d)
            trading_off = set(off.symbols_trading())
            off_flag = {}
            for latest, mem in chains.items():
                off_flag[latest] = any((m in trading_off) and eligible_one(off, m, funds) for m in mem)
        with symbol_links.override(enabled=True):
            on = MemoryAsOfView(conn, d)
            trading_on = set(on.symbols_trading())
            on_flag = {latest: (latest in trading_on) and eligible_one(on, latest, funds) for latest in chains}
            if d in check_days:
                elig = set(eligible_symbols(on, CFG.universe))
                sample_check["sessions_checked"] += 1
                sample_check["mismatches"] += sum(1 for latest in chains if (latest in elig) != on_flag[latest])
        y = str(d.year)
        c = per_year.setdefault(y, {"gained": 0, "lost": 0, "eligible_both": 0, "eligible_on": 0, "eligible_off": 0})
        for latest in chains:
            a, b = on_flag[latest], off_flag[latest]
            c["eligible_on"] += int(a)
            c["eligible_off"] += int(b)
            if a and not b:
                c["gained"] += 1
            elif b and not a:
                c["lost"] += 1
            elif a and b:
                c["eligible_both"] += 1
    out["eligibility"] = {"unit": "symbol-sessions (one linked stock on one session)", "sessions": len(ses), "linked_stocks": len(chains), "per_year": per_year,
                          "total_gained": sum(c["gained"] for c in per_year.values()), "total_lost": sum(c["lost"] for c in per_year.values()), "per_stock_check_vs_eligible_symbols": sample_check}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["diff", "pairs", "effect"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--lake")
    a = ap.parse_args(argv)
    conn = open_lake(a.lake or lake_path())
    res = {"diff": diff_harness, "pairs": pair_proofs, "effect": effect}[a.what](conn)
    Path(a.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "stored_runs")}, indent=1, default=str)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
