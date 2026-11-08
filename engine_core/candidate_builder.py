"""Single place that turns symbols into candidate dicts. Used by live pipeline AND backtest simulator."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import select

from data.db.models import CorporateActionsLog, MarketDataLake
from stockbot.data.adjustments import get_adjusted_series
from stockbot.data.indicators import atr
from engine_core.lifecycle_rules import Bar, parabolic_ref_close
from stockbot.data.sector_map import sector_for


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


def bar_context(adj: pd.DataFrame, d, atr_period: int, parabolic_lookback: int):
    """Per-session inputs for ``advance_one_bar`` from an adjusted OHLC frame (as-of ``d``).

    Shared by the Simulator and the random baseline (F6) so both use the identical adjusted price path.
    Returns ``(Bar, atr_value, close_n_ago)`` or ``None`` if ``d`` is not in the frame.
    """
    dt = d.date() if hasattr(d, "date") and callable(getattr(d, "date")) else d
    if dt not in adj.index:
        return None
    a = atr(adj["high_adj"], adj["low_adj"], adj["close_adj"], period=atr_period)
    r = adj.loc[dt]
    if isinstance(r, pd.DataFrame):
        r = r.iloc[-1]
    atr_val = (
        float(a.loc[dt]) if (dt in a.index and pd.notna(a.loc[dt]))
        else (float(a.iloc[-1]) if pd.notna(a.iloc[-1]) else 0.0)
    )
    bar = Bar(float(r.open_adj), float(r.high_adj), float(r.low_adj), float(r.close_adj))
    return bar, atr_val, parabolic_ref_close(list(adj["close_adj"]), parabolic_lookback)
