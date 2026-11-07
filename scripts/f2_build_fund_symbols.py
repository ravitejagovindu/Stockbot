"""scripts/f2_build_fund_symbols.py — list the ETF / fund symbols (INF-prefixed ISIN) from the raw Bhavcopy staging ISINs and the
securities master, mapped to the lake's canonical symbol.  Writes data/reference/fund_etf_symbols.csv.  Read-only on the database."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    con = sqlite3.connect(f"file:{ROOT / 'finsight.db'}?mode=ro", uri=True, timeout=120)
    st = pd.read_sql_query("select symbol, max(isin) isin from market_data_lake_staging where isin like 'INF%' group by symbol", con)
    sm = pd.read_sql_query("select symbol, isin from securities_master where isin like 'INF%'", con)
    imap = pd.read_sql_query("select symbol, canonical_symbol from isin_symbol_map", con)
    canon = dict(zip(imap["symbol"], imap["canonical_symbol"]))
    rows = pd.concat([st, sm]).drop_duplicates("symbol")
    out = pd.concat([rows, pd.DataFrame({"symbol": [canon[s] for s in rows["symbol"] if s in canon and canon[s] != s],
                                         "isin": [i for s, i in zip(rows["symbol"], rows["isin"]) if s in canon and canon[s] != s]})])
    out = out.drop_duplicates("symbol").sort_values("symbol")
    out.to_csv(ROOT / "data/reference/fund_etf_symbols.csv", index=False)
    print(len(out), "fund/ETF symbols;", out.head(8).to_dict("records"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
