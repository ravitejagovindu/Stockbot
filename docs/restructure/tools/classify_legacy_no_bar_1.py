"""Read-only: classify the legacy entries whose dates have no bar in today's lake. Compares the pre-F2 lake backup, today's lake and the raw bhavcopy staging table."""
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(r"F:\Projects\Ravi\StockBot")
R = ROOT / "backtest" / "outputs_recomputed_net"
t = pd.concat([pd.read_csv(p).assign(cfg=p.name[7:13]) for p in sorted(R.glob("trades_CFG-0?_pooled.csv"))], ignore_index=True)
u = t.drop_duplicates(subset=["symbol", "entry_date", "stop", "shares"])
now = sqlite3.connect(f"file:{ROOT / 'finsight.db'}?mode=ro", uri=True, timeout=120)
pre = sqlite3.connect("file:F:/Projects/Ravi/Backups/finsight_pre_F2_2026-11-06.db?mode=ro", uri=True, timeout=120)
cols = [r[1] for r in now.execute("pragma table_info(market_data_lake_staging)")]
print("staging columns:", cols, flush=True)


def row(con, table, sym, d):
    return con.execute(f"select open_raw, high_raw, low_raw, close_raw, volume_raw from {table} where symbol=? and trade_date=?", (sym, d)).fetchone()


def prev_row(con, sym, d):
    return con.execute("select trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw from market_data_lake where symbol=? and trade_date<? order by trade_date desc limit 1", (sym, d)).fetchone()


nifty = [r[0] for r in now.execute("select trade_date from market_data_lake where symbol='NIFTY50_INDEX' and trade_date>='2020-01-01' order by trade_date")]
rows = []
for r in u.itertuples():
    d = str(r.entry_date)
    if row(now, "market_data_lake", r.symbol, d) is not None:
        continue
    p_now = row(pre, "market_data_lake", r.symbol, d)
    pv = prev_row(pre, r.symbol, d)
    stg = row(now, "market_data_lake_staging", r.symbol, d)
    # how many consecutive Nifty sessions around d are missing for the symbol in today's lake
    i = nifty.index(d) if d in nifty else None
    run = 0
    if i is not None:
        j = i
        while j < len(nifty) and row(now, "market_data_lake", r.symbol, nifty[j]) is None and run < 60:
            run += 1
            j += 1
    copy = bool(p_now and pv and tuple(p_now[:4]) == tuple(pv[1:5]) and p_now[4] == pv[5])
    flat = bool(p_now and p_now[0] == p_now[1] == p_now[2] == p_now[3])
    prevc = pv[4] if pv else None
    move = (p_now[3] / prevc - 1) * 100 if (p_now and prevc) else None
    rows.append(dict(symbol=r.symbol, entry_date=d, cfgs=",".join(sorted(set(t[(t.symbol == r.symbol) & (t.entry_date == r.entry_date)].cfg))),
                     in_preF2=p_now is not None, preF2_ohlc_equal_prev=copy, preF2_flat_bar=flat, preF2_vol=(p_now[4] if p_now else None),
                     preF2_close_move_pct=None if move is None else round(move, 2), in_staging_bhavcopy=stg is not None, missing_run_sessions_now=run))
df = pd.DataFrame(rows)
df.to_csv(Path(sys.argv[1]), index=False)
print(len(df), "rows")
print(df[["in_preF2", "preF2_ohlc_equal_prev", "preF2_flat_bar", "in_staging_bhavcopy"]].value_counts().to_string())
print(df.groupby("symbol").agg(n=("entry_date", "size"), first=("entry_date", "min"), last=("entry_date", "max"), run_max=("missing_run_sessions_now", "max")).to_string())
