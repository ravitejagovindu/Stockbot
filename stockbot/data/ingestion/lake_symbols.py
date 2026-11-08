"""Symbol resolution shared by the corporate-action loading tools (extracted from scripts/f2_load_plan.py in restructure Phase 8 so that a package module does not
import a one-off script)."""
from __future__ import annotations

import pandas as pd


def lake_symbol(imap: pd.DataFrame, isin, sym: str, ex: str) -> str:
    """Symbol under which the event's company sits in the lake after the ISIN->canonical mapping."""
    if isinstance(isin, str):
        m = imap[(imap["isin"] == isin) & (imap["first_date"] <= ex) & (imap["last_date"] >= ex)]
        if len(m):
            return m["canonical_symbol"].iloc[0]
        m = imap[imap["isin"] == isin].sort_values("last_date")
        if len(m):
            return m["canonical_symbol"].iloc[-1]
    return sym
