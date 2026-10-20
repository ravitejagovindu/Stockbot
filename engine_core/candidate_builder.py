"""Single place that turns symbols into candidate dicts. Used by live pipeline AND backtest simulator."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import select

from data.db.models import CorporateActionsLog, MarketDataLake
from engine_core.adjustments import get_adjusted_series
from engine_core.sector_map import sector_for


def build_candidate_dicts(session, config: dict, symbols: list[str], eval_date: date) -> list[dict]:
    """Pre-fetch OHLCV + corporate actions for each symbol and return candidate dicts.

    Each returned dict has keys:
        symbol, raw_ohlcv, adjusted_ohlcv, sector, corporate_actions.

    Parameters
    ----------
    session:
        Active SQLAlchemy session (read-only).
    config:
        Full strategy config dict.
    symbols:
        List of NSE ticker symbols to build candidates for.
    eval_date:
        Point-in-time evaluation date; no future data is used.

    Returns
    -------
    list[dict]
        One dict per symbol that has data; symbols with no rows are silently
        skipped.
    """
    lookback = int(config.get("data", {}).get("resistance_lookback_days", 252)) + 30
    out: list[dict] = []
    for sym in symbols:
        rows = session.execute(
            select(MarketDataLake.trade_date, MarketDataLake.open_raw, MarketDataLake.high_raw,
                   MarketDataLake.low_raw, MarketDataLake.close_raw, MarketDataLake.volume_raw)
            .where(MarketDataLake.symbol == sym)
            .where(MarketDataLake.trade_date <= eval_date)
            .order_by(MarketDataLake.trade_date.desc())
            .limit(lookback)
        ).all()
        if not rows:
            continue
        raw = pd.DataFrame(
            [{"trade_date": r.trade_date, "open_raw": float(r.open_raw), "high_raw": float(r.high_raw),
              "low_raw": float(r.low_raw), "close_raw": float(r.close_raw), "volume_raw": int(r.volume_raw)}
             for r in reversed(rows)]
        ).set_index("trade_date")
        corp = [
            {"ex_date": c.ex_date, "action_type": c.action_type,
             "ratio_numerator": c.ratio_numerator, "ratio_denominator": c.ratio_denominator}
            for c in session.execute(
                select(CorporateActionsLog).where(CorporateActionsLog.symbol == sym)
                .order_by(CorporateActionsLog.ex_date)).scalars().all()
        ]
        out.append({
            "symbol": sym,
            "raw_ohlcv": raw,
            "adjusted_ohlcv": get_adjusted_series(raw, corp, as_of_date=eval_date),
            "sector": sector_for(sym),
            "corporate_actions": corp,
        })
    return out
