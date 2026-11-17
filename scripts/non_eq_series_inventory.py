"""scripts/non_eq_series_inventory.py - NON-EQ SERIES, stage 1, Part B: read-only inventory of the series codes in the archived raw Bhavcopy files.

Reads ONLY: the raw files saved by scripts/archive_raw_bhavcopy.py (MANIFEST.csv lists them), the stored trades.json of the six registered runs, and market_data_lake through
``stockbot.data.lake.open_lake`` (read-only).  Writes ONLY under --out (default Claude_Docs/non_eq_series/) and a parsed cache under --cache.  It describes data; it recomputes no result, metric or gate.

  py -3 scripts/non_eq_series_inventory.py [--raw DIR] [--out DIR] [--cache FILE]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RAW = Path(r"F:\Projects\Ravi\StockBotData\raw_bhavcopy")
CACHE = Path(r"F:\Projects\Ravi\StockBotData\derived\bhav_all.pkl")
RUNS = ["near_52w_high/results_4B", "pullback_uptrend/results_run1", "short_term_reversal/results_run1", "lowvol_uptrend/results_run1",
        "riskadj_momentum/results_run1", "riskadj_momentum_daily/results_run1"]
RESTRICTED = ("BE", "BZ")
COLS = {"symbol": ["SYMBOL", "TckrSymb"], "series": ["SERIES", "SctySrs"], "open": ["OPEN", "OPEN_PRICE", "OpnPric"], "high": ["HIGH", "HIGH_PRICE", "HghPric"],
        "low": ["LOW", "LOW_PRICE", "LwPric"], "close": ["CLOSE", "CLOSE_PRICE", "ClsPric"], "prev": ["PREVCLOSE", "PREV_CLOSE", "PrvsClsgPric"],
        "volume": ["TOTTRDQTY", "TTL_TRD_QNTY", "TtlTradgVol"], "trades": ["TOTALTRADES", "NO_OF_TRADES", "TtlNbOfTxsExctd"], "isin": ["ISIN"]}


def parse_file(path: Path, d: date) -> pd.DataFrame:
    raw = path.read_bytes()
    if path.name.lower().endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read([n for n in z.namelist() if n.lower().endswith(".csv")][0])
    df = pd.read_csv(io.BytesIO(raw), dtype=str, skipinitialspace=True)
    df.columns = [str(c).strip() for c in df.columns]
    out = {}
    for k, opts in COLS.items():
        c = next((o for o in opts if o in df.columns), None)
        out[k] = df[c].astype(str).str.strip() if c is not None else None
    res = pd.DataFrame({k: v for k, v in out.items() if v is not None})
    for c in ("open", "high", "low", "close", "prev", "volume", "trades"):
        res[c] = pd.to_numeric(res.get(c), errors="coerce") if c in res else np.nan
    res["isin"] = res["isin"].where(res["isin"].str.len() == 12, other=None) if "isin" in res else None
    res["date"] = d.isoformat()
    return res


def load_all(raw: Path, cache: Path) -> pd.DataFrame:
    rows = {}
    with open(raw / "MANIFEST.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[r["date"]] = r
    ok = {d: r for d, r in rows.items() if r["status"] == "OK"}
    if cache.exists() and cache.stat().st_mtime > (raw / "MANIFEST.csv").stat().st_mtime:
        df = pd.read_pickle(cache)
        if df["date"].nunique() == len(ok):
            return df
    parts = []
    for i, (d, r) in enumerate(sorted(ok.items())):
        parts.append(parse_file(raw / d[:4] / r["file_name"], date.fromisoformat(d)))
        if i % 500 == 0:
            print("parsed", i, d, flush=True)
    df = pd.concat(parts, ignore_index=True)
    for c in ("symbol", "series", "date", "isin"):
        df[c] = df[c].astype("category")
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(cache)
    return df


def md_table(rows: list[dict], cols: list[str] | None = None) -> str:
    if not rows:
        return "(none)\n"
    cols = cols or list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join("" if r.get(c) is None else (f"{r[c]:,.2f}" if isinstance(r[c], float) else str(r[c])) for c in cols) + " |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("--out", default=str(ROOT / "Claude_Docs" / "non_eq_series"))
    ap.add_argument("--cache", default=str(CACHE))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df = load_all(Path(a.raw), Path(a.cache))
    df["series"] = df["series"].astype(str)
    df["date"] = df["date"].astype(str)
    df["symbol"] = df["symbol"].astype(str)
    df["isin"] = df["isin"].astype(object)
    dates = sorted(df["date"].unique())
    res: dict = {"files": len(dates), "rows": int(len(df)), "first": dates[0], "last": dates[-1]}

    # ---- B1 rows per series ------------------------------------------------------------------------------------------------------------
    by_series = df.groupby("series").agg(rows=("symbol", "size"), days=("date", "nunique"), symbols=("symbol", "nunique"), first=("date", "min"), last=("date", "max")).sort_values("rows", ascending=False)
    by_series.to_csv(out / "b1_series_totals.csv")
    per_day = df.groupby(["date", "series"]).size().unstack(fill_value=0)
    per_day.to_csv(out / "b1_rows_per_day_per_series.csv")
    res["b1_series"] = {s: {k: (int(v) if not isinstance(v, str) else v) for k, v in r.items()} for s, r in by_series.iterrows()}
    per_year = per_day.copy()
    per_year.index = [d[:4] for d in per_year.index]
    year_tbl = per_year[[c for c in ("EQ", "BE", "BZ", "BL", "SM", "ST") if c in per_year]].groupby(level=0).mean().round(1)
    year_tbl.to_csv(out / "b1_mean_rows_per_day_by_year.csv")

    # ---- B2 BE/BZ symbols, ISIN-followed --------------------------------------------------------------------------------------------------
    df["key"] = df["isin"].where(df["isin"].notna(), "SYM:" + df["symbol"])
    restricted_keys = set(df.loc[df["series"].isin(RESTRICTED), "key"].unique())
    sub = df[df["key"].isin(restricted_keys)].sort_values(["key", "date"])
    # one series per key per date (EQ wins if two rows ever coexist, then BE, BZ, others)
    rank = {"EQ": 0, "BE": 1, "BZ": 2}
    sub = sub.assign(_r=sub["series"].map(rank).fillna(9)).sort_values(["key", "date", "_r"]).drop_duplicates(["key", "date"])
    rows = []
    for key, g in sub.groupby("key", sort=False):
        ser = g["series"].tolist()
        dts = g["date"].tolist()
        runs = []                                                           # compressed (series class, first, last)
        for s, d in zip(ser, dts):
            cls = s if s in ("EQ", "BE", "BZ") else "OTHER"
            if runs and runs[-1][0] == cls:
                runs[-1][2] = d
            else:
                runs.append([cls, d, d])
        seq = [r[0] for r in runs]
        to_r = any(seq[i] == "EQ" and seq[i + 1] in RESTRICTED for i in range(len(seq) - 1))
        from_r = any(seq[i] in RESTRICTED and seq[i + 1] == "EQ" for i in range(len(seq) - 1))
        d = {"isin": key, "symbols": "/".join(dict.fromkeys(g["symbol"].tolist())), "path": ">".join(seq) if len(seq) <= 12 else ">".join(seq[:12]) + ">...",
             "n_runs": len(seq), "EQ_to_BEBZ": to_r, "BEBZ_to_EQ": from_r, "direction": ("both" if to_r and from_r else "EQ->BE/BZ" if to_r else "BE/BZ->EQ" if from_r else "BE/BZ only (never EQ here)")}
        for s in ("EQ", "BE", "BZ"):
            gs = g[g["series"] == s]
            d[f"{s}_first"], d[f"{s}_last"], d[f"{s}_days"] = (gs["date"].min(), gs["date"].max(), len(gs)) if len(gs) else ("", "", 0)
        rows.append(d)
    inv = pd.DataFrame(rows)
    inv.to_csv(out / "b2_be_bz_symbols.csv", index=False)
    res["b2"] = {"isins_ever_BE_or_BZ": len(inv), "direction": inv["direction"].value_counts().to_dict(),
                 "isins_ever_BZ": int((inv["BZ_days"] > 0).sum()), "isins_ever_BE": int((inv["BE_days"] > 0).sum()),
                 "multi_symbol_isins": int(inv["symbols"].str.contains("/").sum())}

    # ---- B3 SYMBOL_NO_BARS trades ----------------------------------------------------------------------------------------------------------
    from stockbot.data.lake import open_lake
    ses = dates                                                              # archive session calendar (= lake dates)
    eq = df[df["series"] == "EQ"]
    stale = []
    for run in RUNS:
        tj = json.load(open(ROOT / "docs" / "strategies" / run / "run" / "trades.json", encoding="utf-8"))
        for t in tj:
            if t.get("exit_reason") == "SYMBOL_NO_BARS":
                stale.append((run.split("/")[0], t))
    b3 = []
    for strat, t in stale:
        sym, exit_d = t["symbol"], t["exit_date"]
        # the lake stores the LATEST name of a renamed stock on old dates (353,096 rows differ from the raw file's name of the day), so the stock is followed by ISIN
        sr = df.loc[(df["symbol"] == sym) & df["isin"].notna() & df["series"].isin(("EQ", "BE", "BZ")), ["date", "isin"]].sort_values("date")
        before = sr[sr["date"] <= exit_d]
        pick = (before.iloc[-1]["isin"] if len(before) else sr.iloc[0]["isin"]) if len(sr) else None          # the ISIN the name carried on the exit date (else its first one: a linked later name)
        e = eq[(eq["isin"] == pick) & (eq["date"] <= exit_d)] if pick else eq[(eq["symbol"] == sym) & (eq["date"] <= exit_d)]
        last_eq = e["date"].max() if len(e) else None
        r = {"strategy": strat, "symbol": sym, "entry": t["entry_date"], "exit_stale": exit_d, "last_EQ_date": last_eq, "trade_last_close": round(t.get("last_close") or 0, 2)}
        if last_eq is None:
            b3.append(r)
            continue
        row = e[e["date"] == last_eq].iloc[0]
        isin = row["isin"] if pd.notna(row["isin"]) else None
        r["last_EQ_close"] = float(row["close"])
        r["isin"] = isin
        after = df[(df["key"] == (isin if isin else "SYM:" + sym)) & (df["date"] > last_eq)].sort_values("date")
        after_s = [d for d in ses if d > last_eq]
        r["archive_series_after"] = ",".join(sorted(set(after["series"]))) or "none"
        for n in (1, 5, 10, 20):
            if len(after_s) >= n:
                dn = after_s[n - 1]
                x = after[after["date"] == dn]
                r[f"close_s{n}"] = f"{x.iloc[0]['close']:.2f} ({x.iloc[0]['series']})" if len(x) else "no row"
            else:
                r[f"close_s{n}"] = "after archive end"
        w = after[(after["series"].isin(RESTRICTED)) & (after["date"] <= exit_d)]
        r["BEBZ_rows_in_window"] = len(w)
        r["last_BEBZ_close_in_window"] = (f"{w.iloc[-1]['close']:.2f} on {w.iloc[-1]['date']}" if len(w) else "none")
        wb = after[after["series"].isin(RESTRICTED)]
        r["BEBZ_rows_ever_after"] = len(wb)
        r["last_BEBZ_close_ever"] = (f"{wb.iloc[-1]['close']:.2f} on {wb.iloc[-1]['date']}" if len(wb) else "none")
        r["first_EQ_return_date_after"] = (after[after["series"] == "EQ"]["date"].min() if (after["series"] == "EQ").any() else "")
        b3.append(r)
    pd.DataFrame(b3).to_csv(out / "b3_symbol_no_bars_trades.csv", index=False)
    res["b3_n"] = len(b3)

    # ---- B4 coverage: lake gaps the BE/BZ rows would fill ------------------------------------------------------------------------------------------
    con = open_lake()
    lake_cnt = dict(con.execute("select trade_date, count(*) from market_data_lake where symbol not in ('NIFTY50_INDEX','INDIA_VIX') group by trade_date").fetchall())
    con.close()
    eqc = eq.groupby("date").size()
    mism = [(d, int(eqc.get(d, 0)), int(lake_cnt.get(d, 0))) for d in dates if int(eqc.get(d, 0)) != int(lake_cnt.get(d, 0))]
    res["lake_vs_archive_eq_rowcount_mismatch_days"] = len(mism)
    res["lake_vs_archive_eq_mismatch_examples"] = mism[:10]
    sess_idx = {d: i for i, d in enumerate(ses)}
    eq_keys = eq.assign(key=eq["key"])
    cover = []
    for key, g in eq_keys[eq_keys["key"].isin(restricted_keys)].groupby("key"):
        first_eq, last_eq = g["date"].min(), g["date"].max()
        eqset = set(g["date"])
        rb = sub[(sub["key"] == key) & (sub["series"].isin(RESTRICTED))]
        internal = [d for d in rb["date"] if first_eq < d < last_eq and d not in eqset]
        trailing = [d for d in rb["date"] if d > last_eq]
        leading = [d for d in rb["date"] if d < first_eq]
        # EQ-lake sessions the ISIN is missing between first and last EQ date although the file has a row in another series (the gap the BE/BZ rows would fill)
        cover.append({"isin": key, "symbols": "/".join(dict.fromkeys(g["symbol"].astype(str))), "internal_gap_sessions": len(internal), "trailing_sessions_after_last_EQ": len(trailing),
                      "leading_sessions_before_first_EQ": len(leading), "last_EQ": last_eq})
    cov = pd.DataFrame(cover)
    cov.to_csv(out / "b4_coverage_by_isin.csv", index=False)
    res["b4"] = {"isins_with_EQ_and_BEBZ": len(cov),
                 "isins_internal_gap": int((cov["internal_gap_sessions"] > 0).sum()), "internal_gap_sessions": int(cov["internal_gap_sessions"].sum()),
                 "isins_trailing": int((cov["trailing_sessions_after_last_EQ"] > 0).sum()), "trailing_sessions": int(cov["trailing_sessions_after_last_EQ"].sum()),
                 "isins_leading": int((cov["leading_sessions_before_first_EQ"] > 0).sum()), "leading_sessions": int(cov["leading_sessions_before_first_EQ"].sum()),
                 "isins_any": int(((cov["internal_gap_sessions"] + cov["trailing_sessions_after_last_EQ"]) > 0).sum()),
                 "sessions_any_ex_leading": int((cov["internal_gap_sessions"] + cov["trailing_sessions_after_last_EQ"]).sum())}

    # ---- B5 band and volume of BE / BZ rows --------------------------------------------------------------------------------------------------------
    cols_present = sorted(set(df.columns))
    r5 = {"price_band_column_in_files": False, "columns_parsed": cols_present}
    for s in RESTRICTED:
        x = df[(df["series"] == s) & df["prev"].notna() & (df["prev"] > 0)].copy()
        x["ret"] = (x["close"] / x["prev"] - 1) * 100
        x["rng"] = (x["high"] - x["low"]) / x["prev"] * 100
        x["val"] = x["close"] * x["volume"]
        ar = x["ret"].abs()
        r5[s] = {"rows": int(len(x)), "median_volume": float(x["volume"].median()), "p10_volume": float(x["volume"].quantile(.1)), "p90_volume": float(x["volume"].quantile(.9)),
                 "median_traded_value_inr": float(x["val"].median()), "p10_traded_value_inr": float(x["val"].quantile(.1)), "p90_traded_value_inr": float(x["val"].quantile(.9)),
                 "median_trades": float(x["trades"].median()), "zero_volume_rows": int((x["volume"] == 0).sum()),
                 "abs_close_ret_pct_p50": float(ar.quantile(.5)), "p90": float(ar.quantile(.9)), "p99": float(ar.quantile(.99)), "max": float(ar.max()),
                 "share_abs_ret_ge_4.9pct": float((ar >= 4.9).mean()), "share_abs_ret_ge_9.9pct": float((ar >= 9.9).mean()), "share_abs_ret_ge_19.9pct": float((ar >= 19.9).mean()),
                 "median_hl_range_pct_of_prev": float(x["rng"].median())}
        # most common exact limit seen per symbol-run (the largest |move| rounded to 5 / 10 / 20) - evidence of the band, not the band itself
        mx = x.groupby("key")["ret"].agg(lambda v: max(abs(v.max()), abs(v.min())))
        r5[s]["per_isin_max_abs_ret_bucket"] = {"<=5.2": int((mx <= 5.2).sum()), "5.2-10.2": int(((mx > 5.2) & (mx <= 10.2)).sum()), "10.2-20.2": int(((mx > 10.2) & (mx <= 20.2)).sum()), ">20.2": int((mx > 20.2).sum())}
    res["b5"] = r5
    (out / "inventory.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")

    # ---- markdown fragments for the report ---------------------------------------------------------------------------------------------------------
    top = inv.sort_values("BE_days", ascending=False).head(25)[["isin", "symbols", "direction", "EQ_first", "EQ_last", "BE_first", "BE_last", "BE_days", "BZ_first", "BZ_last", "BZ_days"]]
    (out / "fragments.md").write_text(
        "### B1 series totals\n" + md_table([{"series": s, **{k: v for k, v in r.items()}} for s, r in res["b1_series"].items()][:20]) +
        "\n### B1 mean rows per day by year\n" + md_table([{"year": y, **{c: float(v) for c, v in r.items()}} for y, r in year_tbl.iterrows()]) +
        "\n### B2 directions\n" + md_table([{"direction": k, "isins": v} for k, v in res["b2"]["direction"].items()]) +
        "\n### B2 25 longest BE histories\n" + md_table(top.to_dict("records")) +
        "\n### B3\n" + md_table(b3) + "\n### B4\n" + json.dumps(res["b4"], indent=1) + "\n### B5\n" + json.dumps(res["b5"], indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("files", "rows", "first", "last", "b2", "b3_n", "b4", "lake_vs_archive_eq_rowcount_mismatch_days")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
