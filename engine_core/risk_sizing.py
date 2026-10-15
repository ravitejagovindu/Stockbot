"""
FInsight Trading Engine — Risk & Position Sizing Engine
=======================================================
This module computes trade setup parameters (entry, stops, target, shares)
for each candidate that passed the universe screen.

Sizing Logic
------------
For each candidate:

1. **Stop A** = ``entry_price - (atr_stop_multiplier × ATR14(adjusted))``
2. **Stop B** = ``donchian_low(adjusted_low, donchian_period)`` (structural low)
3. **Live Stop Loss** = ``min(stop_a, stop_b)``  [lower price = wider stop]
4. **Resistance Target** = ``donchian_high(adjusted_high, 252)``
5. **Projected R:R** = ``(target - entry) / (entry - live_stop)``
   → Reject if R:R < ``min_rr_ratio``
6. **Shares** = ``floor((account_equity × max_loss_pct_per_trade/100) / (entry - live_stop))``
7. **Heat Cap Gates** (evaluated sequentially across candidates):
   - Total open positions < ``max_concurrent_positions``
   - Total portfolio risk < ``max_total_portfolio_risk_pct`` of equity
   - Sector exposure < ``max_sector_exposure_pct`` of total allocated capital

Heat Cap Sequentiality
----------------------
The heat cap gate is evaluated **in candidate order**, not independently.
Once any heat cap threshold is projected to be breached by adding a new
position, all subsequent candidates (regardless of their individual quality)
are blocked.  This preserves capital discipline and prevents over-sizing
in fast-moving markets.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from engine_core.adjustments import get_adjusted_series
from engine_core.indicators import atr, donchian_high, donchian_low

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TradeSetup dataclass
# ---------------------------------------------------------------------------

@dataclass
class TradeSetup:
    """All computed parameters for a candidate trade entry.

    Attributes
    ----------
    symbol:
        NSE ticker symbol.
    eval_date:
        Evaluation / screening date.
    entry_price:
        Proposed entry price (adjusted close of the screening date).
    live_stop_loss:
        Effective stop-loss price — the lower (wider) of stop_a and stop_b.
    stop_a:
        ATR-based stop: ``entry_price - (atr_multiplier × ATR14)``.
    stop_b:
        Donchian channel low over the configured period.
    initial_resistance_target:
        First structural resistance above entry (52-week Donchian high).
    shares:
        Number of shares to buy such that the trade risks ≤ 1% of equity.
    position_value:
        ``shares × entry_price`` (in rupees).
    risk_amount:
        ``shares × (entry_price - live_stop_loss)`` (in rupees).
    risk_pct_of_equity:
        ``risk_amount / account_equity × 100`` (percentage).
    projected_rr:
        ``(target - entry) / (entry - live_stop_loss)``.
    blocked:
        ``True`` if any gate (R:R or heat cap) rejected this setup.
    block_reason:
        Short description of why the setup was blocked, or ``None``.
    sector:
        Sector of the symbol (passed in from candidate list), or ``None``.
    """

    symbol: str
    eval_date: date
    entry_price: float
    live_stop_loss: float
    stop_a: float
    stop_b: float
    initial_resistance_target: float
    shares: int
    position_value: float
    risk_amount: float
    risk_pct_of_equity: float
    projected_rr: float
    blocked: bool
    block_reason: Optional[str]
    sector: Optional[str] = None


# ---------------------------------------------------------------------------
# RiskAndSizingEngine class
# ---------------------------------------------------------------------------

class RiskAndSizingEngine:
    """Stateless per-candidate sizing engine.

    Parameters
    ----------
    config:
        Full strategy config dict.  Uses ``risk`` sub-dict and
        ``data.resistance_lookback_days``.
    """

    def __init__(self, config: dict) -> None:
        """Initialise using the ``risk`` block from ``strategy_config.yaml``."""
        risk = config["risk"]
        data_cfg = config.get("data", {})

        self._atr_period: int = int(risk["atr_period"])
        self._atr_stop_mult: float = float(risk["atr_stop_multiplier"])
        self._donchian_period: int = int(risk["donchian_period"])
        self._resistance_lookback: int = int(
            data_cfg.get("resistance_lookback_days", 252)
        )
        self._max_loss_pct: float = float(risk["max_loss_pct_per_trade"])  # e.g. 1.0
        self._min_rr: float = float(risk["min_rr_ratio"])  # e.g. 1.5
        self._max_positions: int = int(risk["max_concurrent_positions"])
        self._max_positions_bull: int = int(
            risk.get("max_concurrent_positions_bull", self._max_positions)
        )
        self._max_total_risk_pct: float = float(risk["max_total_portfolio_risk_pct"])
        self._max_sector_pct: float = float(risk["max_sector_exposure_pct"])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_setup(
        self,
        symbol: str,
        eval_date: date,
        adjusted_ohlcv: pd.DataFrame,
        raw_ohlcv: pd.DataFrame,
        account_equity: float,
        current_positions: list[dict],
        sector: Optional[str] = None,
        max_positions: Optional[int] = None,
    ) -> TradeSetup:
        """Compute a single candidate's trade setup.

        Parameters
        ----------
        symbol:
            NSE ticker.
        eval_date:
            Screening date.
        adjusted_ohlcv:
            In-memory adjusted OHLCV DataFrame with columns:
            ``open_adj``, ``high_adj``, ``low_adj``, ``close_adj``.
        raw_ohlcv:
            Raw OHLCV DataFrame (used for reference only here — ADTV /
            market cap were already computed in the screener).
        account_equity:
            Total account equity in rupees.
        current_positions:
            List of currently open position dicts.  Each must contain:
            ``risk_amount`` (float), ``sector`` (str|None),
            ``position_value`` (float).
        sector:
            Sector for the candidate symbol.

        Returns
        -------
        TradeSetup
            Fully computed setup; ``blocked=True`` if any gate fails.
        """
        adj_close = adjusted_ohlcv["close_adj"]
        adj_high = adjusted_ohlcv["high_adj"]
        adj_low = adjusted_ohlcv["low_adj"]

        entry_price = float(adj_close.iloc[-1])

        # ------------------------------------------------------------------
        # Step 1 & 2: Compute stops
        # ------------------------------------------------------------------
        atr_series = atr(adj_high, adj_low, adj_close, period=self._atr_period)
        latest_atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else None

        if latest_atr is None:
            return TradeSetup(
                symbol=symbol,
                eval_date=eval_date,
                entry_price=entry_price,
                live_stop_loss=0.0,
                stop_a=0.0,
                stop_b=0.0,
                initial_resistance_target=0.0,
                shares=0,
                position_value=0.0,
                risk_amount=0.0,
                risk_pct_of_equity=0.0,
                projected_rr=0.0,
                blocked=True,
                block_reason="ATR_NAN",
                sector=sector,
            )

        stop_a = entry_price - (self._atr_stop_mult * latest_atr)

        donchian_low_series = donchian_low(adj_low, period=self._donchian_period)
        latest_donchian_low = donchian_low_series.iloc[-1]
        if pd.isna(latest_donchian_low):
            return TradeSetup(
                symbol=symbol,
                eval_date=eval_date,
                entry_price=entry_price,
                live_stop_loss=0.0,
                stop_a=stop_a,
                stop_b=0.0,
                initial_resistance_target=0.0,
                shares=0,
                position_value=0.0,
                risk_amount=0.0,
                risk_pct_of_equity=0.0,
                projected_rr=0.0,
                blocked=True,
                block_reason="DONCHIAN_LOW_NAN",
                sector=sector,
            )

        stop_b = float(latest_donchian_low)

        # Live stop = the lower (wider) price — max(distance) = min(price)
        live_stop_loss = min(stop_a, stop_b)

        # Guard: stop must be strictly below entry
        risk_per_share = entry_price - live_stop_loss
        if risk_per_share <= 0:
            return TradeSetup(
                symbol=symbol,
                eval_date=eval_date,
                entry_price=entry_price,
                live_stop_loss=live_stop_loss,
                stop_a=stop_a,
                stop_b=stop_b,
                initial_resistance_target=0.0,
                shares=0,
                position_value=0.0,
                risk_amount=0.0,
                risk_pct_of_equity=0.0,
                projected_rr=0.0,
                blocked=True,
                block_reason="STOP_ABOVE_ENTRY",
                sector=sector,
            )

        # ------------------------------------------------------------------
        # Step 4: Resistance target (52-week Donchian high)
        # ------------------------------------------------------------------
        donchian_high_series = donchian_high(adj_high, period=self._resistance_lookback)
        latest_donchian_high = donchian_high_series.iloc[-1]
        if pd.isna(latest_donchian_high):
            return TradeSetup(
                symbol=symbol,
                eval_date=eval_date,
                entry_price=entry_price,
                live_stop_loss=live_stop_loss,
                stop_a=stop_a,
                stop_b=stop_b,
                initial_resistance_target=0.0,
                shares=0,
                position_value=0.0,
                risk_amount=0.0,
                risk_pct_of_equity=0.0,
                projected_rr=0.0,
                blocked=True,
                block_reason="DONCHIAN_HIGH_NAN",
                sector=sector,
            )

        resistance_target = float(latest_donchian_high)

        # Extended target: if entry is AT or ABOVE the 52-week high the stock
        # is in price discovery with no overhead supply.  The Donchian target
        # would be at or below entry (0 reward), which produces a false R:R.
        # Instead we project forward using 3 × ATR from entry.
        atr_projection_mult = 3.0
        if entry_price >= resistance_target and latest_atr is not None:
            resistance_target = entry_price + atr_projection_mult * latest_atr
            logger.debug(
                "[RiskSizing] %s is in price discovery. "
                "Using ATR-projected target %.2f instead of Donchian high %.2f.",
                symbol, resistance_target, float(latest_donchian_high),
            )

        # ------------------------------------------------------------------
        # Step 5: Projected R:R
        # ------------------------------------------------------------------
        reward = resistance_target - entry_price
        projected_rr = reward / risk_per_share if risk_per_share > 0 else 0.0

        if projected_rr < self._min_rr:
            return TradeSetup(
                symbol=symbol,
                eval_date=eval_date,
                entry_price=entry_price,
                live_stop_loss=live_stop_loss,
                stop_a=stop_a,
                stop_b=stop_b,
                initial_resistance_target=resistance_target,
                shares=0,
                position_value=0.0,
                risk_amount=0.0,
                risk_pct_of_equity=0.0,
                projected_rr=projected_rr,
                blocked=True,
                block_reason=f"RR_TOO_LOW({projected_rr:.2f}<{self._min_rr})",
                sector=sector,
            )

        # ------------------------------------------------------------------
        # Step 6: Position size
        # ------------------------------------------------------------------
        capital_at_risk = account_equity * (self._max_loss_pct / 100.0)
        shares = math.floor(capital_at_risk / risk_per_share)

        if shares < 1:
            return TradeSetup(
                symbol=symbol,
                eval_date=eval_date,
                entry_price=entry_price,
                live_stop_loss=live_stop_loss,
                stop_a=stop_a,
                stop_b=stop_b,
                initial_resistance_target=resistance_target,
                shares=0,
                position_value=0.0,
                risk_amount=0.0,
                risk_pct_of_equity=0.0,
                projected_rr=projected_rr,
                blocked=True,
                block_reason="ZERO_SHARES",
                sector=sector,
            )

        position_value = shares * entry_price
        risk_amount = shares * risk_per_share
        risk_pct_of_equity = risk_amount / account_equity * 100.0

        # ------------------------------------------------------------------
        # Step 7: Heat cap (projected) — caller must check this sequentially
        # ------------------------------------------------------------------
        block_reason = self._check_heat_cap(
            sector=sector,
            position_value=position_value,
            risk_amount=risk_amount,
            account_equity=account_equity,
            current_positions=current_positions,
            max_positions=max_positions,
        )

        blocked = block_reason is not None

        return TradeSetup(
            symbol=symbol,
            eval_date=eval_date,
            entry_price=entry_price,
            live_stop_loss=live_stop_loss,
            stop_a=stop_a,
            stop_b=stop_b,
            initial_resistance_target=resistance_target,
            shares=shares,
            position_value=position_value,
            risk_amount=risk_amount,
            risk_pct_of_equity=risk_pct_of_equity,
            projected_rr=projected_rr,
            blocked=blocked,
            block_reason=block_reason,
            sector=sector,
        )

    def compute_all(
        self,
        candidates: list[dict],
        eval_date: date,
        account_equity: float,
        current_positions: list[dict],
        session: Optional[Any] = None,
        is_bull_regime: Optional[bool] = None,
        max_positions: Optional[int] = None,
    ) -> list[TradeSetup]:
        """Compute setups for all candidates sequentially.

        The heat cap gate is applied cumulatively: as each non-blocked setup
        is accepted, it is added to the "virtual" position list for all
        subsequent candidates.  Once any heat cap threshold is projected to be
        breached, all remaining candidates are blocked.

        Parameters
        ----------
        candidates:
            List of candidate dicts.  Each must contain:
            ``symbol`` (str), and optionally ``corporate_actions`` (list),
            ``raw_ohlcv`` (pd.DataFrame), ``adjusted_ohlcv`` (pd.DataFrame),
            ``sector`` (str|None).
        eval_date:
            Screening date.
        account_equity:
            Total account equity.
        current_positions:
            Currently open positions (before today's new entries).
        session:
            Optional DB session to detect regime state.
        is_bull_regime:
            Optional override for bull regime position cap.
        max_positions:
            Optional explicit cap on open positions.

        Returns
        -------
        list[TradeSetup]
            One entry per candidate, in the same order as input.
        """
        results: list[TradeSetup] = []
        # Rolling position list for sequential heat cap evaluation
        virtual_positions = list(current_positions)
        heat_cap_full = False

        if max_positions is None:
            if is_bull_regime is None and session is not None:
                is_bull_regime = self._is_bull_regime(eval_date, session)
            effective_max_positions = (
                self._max_positions_bull if is_bull_regime else self._max_positions
            )
        else:
            effective_max_positions = max_positions

        for candidate in candidates:
            symbol = candidate["symbol"]
            sector = candidate.get("sector")
            adjusted_ohlcv = candidate.get("adjusted_ohlcv", pd.DataFrame())
            raw_ohlcv = candidate.get("raw_ohlcv", pd.DataFrame())

            if adjusted_ohlcv.empty or raw_ohlcv.empty:
                results.append(
                    TradeSetup(
                        symbol=symbol,
                        eval_date=eval_date,
                        entry_price=0.0,
                        live_stop_loss=0.0,
                        stop_a=0.0,
                        stop_b=0.0,
                        initial_resistance_target=0.0,
                        shares=0,
                        position_value=0.0,
                        risk_amount=0.0,
                        risk_pct_of_equity=0.0,
                        projected_rr=0.0,
                        blocked=True,
                        block_reason="NO_OHLCV_DATA",
                        sector=sector,
                    )
                )
                continue

            if heat_cap_full:
                # Entire cap is full — block remaining candidates immediately
                results.append(
                    TradeSetup(
                        symbol=symbol,
                        eval_date=eval_date,
                        entry_price=float(adjusted_ohlcv["close_adj"].iloc[-1]),
                        live_stop_loss=0.0,
                        stop_a=0.0,
                        stop_b=0.0,
                        initial_resistance_target=0.0,
                        shares=0,
                        position_value=0.0,
                        risk_amount=0.0,
                        risk_pct_of_equity=0.0,
                        projected_rr=0.0,
                        blocked=True,
                        block_reason="BLOCKED_BY_RISK",
                        sector=sector,
                    )
                )
                continue

            setup = self.compute_setup(
                symbol=symbol,
                eval_date=eval_date,
                adjusted_ohlcv=adjusted_ohlcv,
                raw_ohlcv=raw_ohlcv,
                account_equity=account_equity,
                current_positions=virtual_positions,
                sector=sector,
                max_positions=effective_max_positions,
            )
            results.append(setup)

            # If this setup passed all gates, add it to the virtual portfolio
            # so subsequent candidates see a more constrained heat cap.
            if not setup.blocked:
                virtual_positions = virtual_positions + [
                    {
                        "symbol": setup.symbol,
                        "sector": setup.sector,
                        "position_value": setup.position_value,
                        "risk_amount": setup.risk_amount,
                    }
                ]
                # Re-check if cap is now full for future candidates
                heat_cap_full = self._is_heat_cap_full(
                    virtual_positions, account_equity, max_positions=effective_max_positions
                )

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_bull_regime(
        self, eval_date: date, session: Optional[Any] = None
    ) -> bool:
        """Check if market is in confirmed bull regime (kill switch OFF and Nifty > 200 SMA)."""
        if session is None:
            return False
        try:
            from sqlalchemy import select
            from data.db.models import RegimeState as DBRegimeState
            row = (
                session.execute(
                    select(
                        DBRegimeState.kill_switch_active,
                        DBRegimeState.nifty_close,
                        DBRegimeState.nifty_sma200,
                    )
                    .where(DBRegimeState.eval_date <= eval_date)
                    .order_by(DBRegimeState.eval_date.desc())
                    .limit(1)
                )
                .first()
            )
            if row and not row.kill_switch_active:
                if row.nifty_close and row.nifty_sma200 and row.nifty_close > row.nifty_sma200:
                    return True
        except Exception:
            pass
        return False

    def _check_heat_cap(
        self,
        sector: Optional[str],
        position_value: float,
        risk_amount: float,
        account_equity: float,
        current_positions: list[dict],
        max_positions: Optional[int] = None,
    ) -> Optional[str]:
        """Return a block reason string if any heat cap gate is breached.

        Parameters
        ----------
        sector:
            Sector of the new candidate.
        position_value:
            Projected position value of the new candidate.
        risk_amount:
            Projected risk amount of the new candidate.
        account_equity:
            Total account equity.
        current_positions:
            Positions already open (or virtually accepted earlier in the run).
        max_positions:
            Optional effective cap on open positions.

        Returns
        -------
        str or None
            Block reason if any gate is breached, else ``None``.
        """
        # Gate A: position count
        allowed_max = max_positions if max_positions is not None else self._max_positions
        projected_positions = len(current_positions) + 1
        if projected_positions > allowed_max:
            return (
                f"BLOCKED_BY_RISK(positions:{projected_positions}>{allowed_max})"
            )

        # Gate B: total portfolio risk
        existing_risk = sum(p.get("risk_amount", 0.0) for p in current_positions)
        projected_total_risk = existing_risk + risk_amount
        projected_risk_pct = projected_total_risk / account_equity * 100.0
        if projected_risk_pct > self._max_total_risk_pct:
            return (
                f"BLOCKED_BY_RISK(total_risk:{projected_risk_pct:.1f}%>{self._max_total_risk_pct}%)"
            )

        # Gate C: sector exposure
        if sector:
            sector_positions = [
                p for p in current_positions if p.get("sector") == sector
            ]
            total_allocated = sum(
                p.get("position_value", 0.0) for p in current_positions
            ) + position_value  # include the new position in the denominator
            sector_capital = sum(
                p.get("position_value", 0.0) for p in sector_positions
            ) + position_value

            if total_allocated > 0:
                sector_pct = sector_capital / total_allocated * 100.0
                if sector_pct > self._max_sector_pct:
                    return (
                        f"BLOCKED_BY_RISK(sector_{sector}:{sector_pct:.1f}%"
                        f">{self._max_sector_pct}%)"
                    )

        return None  # All gates passed

    def _is_heat_cap_full(
        self,
        positions: list[dict],
        account_equity: float,
        max_positions: Optional[int] = None,
    ) -> bool:
        """Return True if adding any more positions would breach any heat cap."""
        allowed_max = max_positions if max_positions is not None else self._max_positions
        if len(positions) >= allowed_max:
            return True
        total_risk = sum(p.get("risk_amount", 0.0) for p in positions)
        if total_risk / account_equity * 100.0 >= self._max_total_risk_pct:
            return True
        return False
