import sqlite3, pandas as pd
from pathlib import Path
SP=Path(r"C:\Users\ravit\AppData\Local\Temp\claude\02ca8bb3de4e43f2\12d280e4-1f6d-4861-bf0d-b2bd814228e2\scratchpad")
d=pd.read_csv(SP/"classify90.csv")
now=sqlite3.connect("file:F:/Projects/Ravi/StockBot/finsight.db?mode=ro",uri=True,timeout=120)
sess=set(r[0] for r in now.execute("select trade_date from market_data_lake where symbol='NIFTY50_INDEX' and trade_date>='2021-01-01'"))
first={s:now.execute("select min(trade_date),max(trade_date),count(*) from market_data_lake where symbol=?",(s,)).fetchone() for s in d.symbol.unique()}
def cat(r):
    if r.entry_date not in sess: return "A. not an NSE session today (holiday): synthetic flat bar in the pre-swap lake"
    if first[r.symbol][0] > r.entry_date: return "D. symbol did not exist under this name in today's lake yet (rename artifact)"
    if r.preF2_flat_bar and abs(r.preF2_close_move_pct) >= 4.5: return "B. circuit-locked flat bar (O=H=L=C, about -5% on the day): no trade can have happened"
    if r.preF2_flat_bar: return "A2. flat bar with no move"
    if r.missing_run_sessions_now >= 5: return "C. absent from the EQ-only bhavcopy for 5+ consecutive sessions (non-EQ series / restricted segment period), pre-swap lake had Yahoo bars"
    return "E. other"
d["category"]=d.apply(cat,axis=1)
d["lake_first_date"]=d.symbol.map(lambda s:first[s][0])
d.to_csv(Path(r"F:\Projects\Ravi\StockBot\docs\restructure\baseline\legacy_trades_without_bar.csv"),index=False)
print(d.category.value_counts().to_string())
g=d.groupby(["category","symbol"]).agg(n=("entry_date","size"),first=("entry_date","min"),last=("entry_date","max"),run=("missing_run_sessions_now","max")).reset_index()
print(g.to_string(index=False))
