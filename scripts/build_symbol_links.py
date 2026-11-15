"""Build data/reference/symbol_links.csv (the accepted renames) and symbol_links_not_linked.csv (every other boundary of data/reference/isin_symbol_map.csv, with the reason).

  py -3 scripts/build_symbol_links.py [--lake PATH] [--out-dir data/reference]

Inputs (read-only): data/reference/isin_symbol_map.csv (one row per ISIN x symbol segment, with the boundary type to the next segment), the lake's market_data_lake (first and last bar and
their closes per symbol; opened with sqlite mode=ro&immutable=1) and corporate_actions_log (SPLIT/BONUS rows of either symbol). Nothing is written to the lake.

A pair (old -> new) is LINKED only if ALL hold (numbers fixed by the owner):
  1. same ISIN (the two rows of the map belong to one ISIN) and map boundary type ``pure_rename``;
  2. both symbols exist in the lake; the new symbol's first bar is 1 to 5 sessions after the old symbol's last bar (sessions = positions in the lake's calendar, the distinct trade dates);
  3. no overlapping bars: the old symbol's last bar is before the new symbol's first bar;
  4. boundary ratio = first close of the new symbol / (last close of the old symbol x factor) is between 0.80 and 1.25, where factor = product of the SPLIT/BONUS price factors
     (stockbot.data.adjustments.action_factor) of rows filed under either symbol with ex-date after the old last bar and up to the new first bar (a split whose ex-date IS the old last bar
     is already in that bar and is not applied again);
  5. unambiguous: a symbol is the old side of at most one accepted pair and the new side of at most one.
Chains (A -> B -> C) resolve to the latest symbol (column ``latest_symbol``). Everything else is written to the not-linked file; nothing in it is linked.
Deterministic: same inputs, same bytes.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stockbot.data.adjustments import action_factor  # noqa: E402

DEFAULT_LAKE = "F:/Projects/Ravi/StockBot/finsight.db"
MIN_SESSIONS, MAX_SESSIONS = 1, 5
RATIO_LO, RATIO_HI = 0.80, 1.25
LINK_COLS = ["old_symbol", "new_symbol", "latest_symbol", "isin", "old_last_bar", "new_first_bar", "sessions_between", "split_bonus_factor", "boundary_ratio_after_factor"]
NOT_COLS = ["old_symbol", "new_symbol", "isin", "map_boundary_type", "map_boundary_reason", "old_last_bar", "new_first_bar", "sessions_between", "split_bonus_factor", "boundary_ratio_after_factor", "reason"]


def build(lake: str, isin_map: pd.DataFrame) -> tuple:
    con = sqlite3.connect(f"file:{lake}?mode=ro&immutable=1", uri=True)
    cal = [r[0] for r in con.execute("select distinct trade_date from market_data_lake order by 1")]
    pos = {d: i for i, d in enumerate(cal)}
    ca = pd.read_sql("select symbol, ex_date, action_type, ratio_numerator, ratio_denominator from corporate_actions_log where action_type in ('SPLIT','BONUS')", con)
    ca_by = {s: g for s, g in ca.groupby("symbol")}

    def span(sym):
        r = con.execute("select min(trade_date), max(trade_date) from market_data_lake where symbol=?", (sym,)).fetchone()
        if r[0] is None:
            return None
        first_close = con.execute("select close_raw from market_data_lake where symbol=? and trade_date=?", (sym, r[0])).fetchone()[0]
        last_close = con.execute("select close_raw from market_data_lake where symbol=? and trade_date=?", (sym, r[1])).fetchone()[0]
        return {"first": r[0], "last": r[1], "first_close": float(first_close), "last_close": float(last_close)}

    spans = {}
    accepted, rejected = [], []
    m = isin_map.sort_values(["isin", "segment"]).reset_index(drop=True)
    for isin, g in m.groupby("isin", sort=True):
        g = g.reset_index(drop=True)
        for i in range(len(g) - 1):
            a, b = g.iloc[i], g.iloc[i + 1]
            row = {"old_symbol": a["symbol"], "new_symbol": b["symbol"], "isin": isin, "map_boundary_type": a["boundary_to_next"], "map_boundary_reason": a["boundary_reason"],
                   "old_last_bar": None, "new_first_bar": None, "sessions_between": None, "split_bonus_factor": None, "boundary_ratio_after_factor": None}
            for s in (a["symbol"], b["symbol"]):
                if s not in spans:
                    spans[s] = span(s)
            sa, sb = spans[a["symbol"]], spans[b["symbol"]]
            if sa is not None and sb is not None:
                row["old_last_bar"], row["new_first_bar"] = sa["last"], sb["first"]
                row["sessions_between"] = pos[sb["first"]] - pos[sa["last"]]
                f = 1.0
                if row["sessions_between"] > 0:
                    for s in (a["symbol"], b["symbol"]):
                        if s in ca_by:
                            for x in ca_by[s].itertuples():
                                if sa["last"] < x.ex_date <= sb["first"]:
                                    try:
                                        f *= action_factor({"action_type": x.action_type, "ratio_numerator": x.ratio_numerator, "ratio_denominator": x.ratio_denominator})
                                    except ValueError:
                                        pass
                row["split_bonus_factor"] = f
                row["boundary_ratio_after_factor"] = sb["first_close"] / (sa["last_close"] * f)
            reason = None
            if a["boundary_to_next"] != "pure_rename":
                reason = f"map boundary type {a['boundary_to_next']}: {a['boundary_reason']}"
            elif sa is None or sb is None:
                reason = "a symbol of the pair has no bars in the lake"
            elif row["sessions_between"] <= 0 or sb["first"] <= sa["last"]:
                reason = "overlapping bars (the new symbol's first bar is not after the old symbol's last bar)"
            elif not (MIN_SESSIONS <= row["sessions_between"] <= MAX_SESSIONS):
                reason = f"new first bar is {row['sessions_between']} sessions after the old last bar (allowed {MIN_SESSIONS} to {MAX_SESSIONS})"
            elif not (RATIO_LO <= row["boundary_ratio_after_factor"] <= RATIO_HI):
                reason = f"boundary ratio {row['boundary_ratio_after_factor']:.4f} outside {RATIO_LO} to {RATIO_HI}"
            (rejected if reason else accepted).append({**row, "reason": reason} if reason else row)
    # unambiguous: at most one successor per old symbol and one predecessor per new symbol
    acc = pd.DataFrame(accepted, columns=NOT_COLS[:-1])
    drop = set()
    for col in ("old_symbol", "new_symbol"):
        dup = acc[acc.duplicated(col, keep=False)]
        for r in dup.itertuples():
            drop.add((r.old_symbol, r.new_symbol))
    kept = []
    for r in accepted:
        if (r["old_symbol"], r["new_symbol"]) in drop:
            rejected.append({**r, "reason": "ambiguous: the old or the new symbol is part of more than one otherwise acceptable pair"})
        else:
            kept.append(r)
    nxt = {r["old_symbol"]: r["new_symbol"] for r in kept}

    def latest(s):
        seen = {s}
        while s in nxt:
            s = nxt[s]
            if s in seen:
                raise ValueError(f"link cycle at {s}")
            seen.add(s)
        return s
    for r in kept:
        r["latest_symbol"] = latest(r["old_symbol"])
    con.close()
    links = pd.DataFrame(kept, columns=LINK_COLS).sort_values(["latest_symbol", "old_last_bar", "old_symbol"]).reset_index(drop=True)
    notl = pd.DataFrame(rejected, columns=NOT_COLS).sort_values(["map_boundary_type", "old_symbol", "new_symbol"]).reset_index(drop=True)
    return links, notl


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default=DEFAULT_LAKE)
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "reference"))
    a = ap.parse_args(argv)
    isin_map = pd.read_csv(ROOT / "data" / "reference" / "isin_symbol_map.csv")
    links, notl = build(a.lake, isin_map)
    out = Path(a.out_dir)
    links.to_csv(out / "symbol_links.csv", index=False, float_format="%.6f", lineterminator="\n")
    notl.to_csv(out / "symbol_links_not_linked.csv", index=False, float_format="%.6f", lineterminator="\n")
    print(f"linked pairs: {len(links)}; stocks (latest symbols): {links['latest_symbol'].nunique()}; not linked boundaries: {len(notl)}")
    print(notl["map_boundary_type"].value_counts().to_string())
    print(notl["reason"].str.replace(r"[0-9.]+", "N", regex=True).str.slice(0, 70).value_counts().head(12).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
