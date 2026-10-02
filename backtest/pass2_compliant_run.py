"""
FInsight Trading Engine — Pass 2 Compliant Run
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class Pass2CompliantRun:
    """
    Re-runs the engine ingesting verified historical data and dropping non-compliant trades.
    """

    def __init__(self, config: dict):
        self.config = config

    def run(
        self,
        regime_name: str,
        candidate_trades_path: str,
        verified_asm_gsm_path: str,
        historical_earnings_path: str,
        initial_equity: float,
        session: Session
    ) -> dict:
        """
        Loads trades, drops those in ASM/GSM or with earnings within 14 days,
        and computes final equity curve.
        """
        logger.info(f"Starting Pass 2 Compliant Run for regime: {regime_name}")
        
        candidates = pd.read_csv(candidate_trades_path, parse_dates=["entry_date"])
        
        # Load Verified ASM/GSM
        try:
            asm_df = pd.read_csv(verified_asm_gsm_path)
            if asm_df.empty:
                raise ValueError("empty")
            asm_df = asm_df[asm_df["status"] == "VERIFIED"]
            asm_df["start_date"] = pd.to_datetime(asm_df["start_date"]).dt.date
            asm_df["end_date"] = pd.to_datetime(asm_df["end_date"]).dt.date
        except (FileNotFoundError, pd.errors.EmptyDataError, ValueError):
            logger.warning("No verified ASM/GSM file found. Assuming all clear.")
            asm_df = pd.DataFrame(columns=["symbol", "start_date", "end_date"])

        # Load Historical Earnings
        try:
            earn_df = pd.read_csv(historical_earnings_path)
            earn_df["event_date"] = pd.to_datetime(earn_df["event_date"]).dt.date
        except FileNotFoundError:
            logger.warning("No historical earnings file found. Assuming all clear.")
            earn_df = pd.DataFrame(columns=["symbol", "event_date"])

        # Filter candidates
        valid_trades = []
        dropped_trades = []
        
        block_days = self.config["trade_management"]["binary_event_block_days"]

        for _, trade in candidates.iterrows():
            sym = trade["symbol"]
            entry_date = trade["entry_date"].date()
            
            # Check ASM/GSM
            sym_asm = asm_df[asm_df["symbol"] == sym]
            in_asm = False
            for _, row in sym_asm.iterrows():
                # If end_date is NaT/NaN, assume still in ASM
                end = row["end_date"] if pd.notnull(row["end_date"]) else date(2099, 12, 31)
                if row["start_date"] <= entry_date <= end:
                    in_asm = True
                    break
            
            if in_asm:
                trade["drop_reason"] = "ASM/GSM"
                dropped_trades.append(trade)
                continue

            # Check Earnings
            sym_earn = earn_df[earn_df["symbol"] == sym]
            in_earn = False
            for _, row in sym_earn.iterrows():
                ev_date = row["event_date"]
                if entry_date <= ev_date <= entry_date + timedelta(days=block_days):
                    in_earn = True
                    break

            if in_earn:
                trade["drop_reason"] = "EARNINGS"
                dropped_trades.append(trade)
                continue

            valid_trades.append(trade)

        valid_df = pd.DataFrame(valid_trades)
        dropped_df = pd.DataFrame(dropped_trades)
        
        logger.info(f"Pass 2 complete. {len(valid_trades)} passed, {len(dropped_trades)} dropped.")
        
        # ---------------------------------------------------------
        # REAL EQUITY SIMULATOR
        # ---------------------------------------------------------
        if valid_df.empty:
            logger.warning("No valid trades passed. Equity curve is flat.")
            trading_days = pd.date_range("2020-01-01", periods=2)
            nifty = pd.Series([10000, 10000], index=trading_days)
            equity = pd.Series([initial_equity, initial_equity], index=trading_days)
            return {
                "equity_curve": equity,
                "trades_executed": valid_df,
                "trades_dropped": dropped_df,
                "summary": {
                    "max_drawdown_pct": 0.0,
                    "cagr_pct": 0.0,
                    "nifty_cagr_pct": 0.0,
                    "alpha_pct": 0.0,
                    "sharpe": 0,
                    "total_trades": 0,
                    "win_rate": 0.0,
                }
            }

        # 1. Fetch Nifty calendar and prices
        from sqlalchemy import select
        from data.db.models import MarketDataLake
        
        nifty_sym = self.config["data"].get("nifty_symbol", "NIFTY50_INDEX")
        # We need the regime start/end. Pass2 run() doesn't have start/end args!
        # But we know entry dates from candidates.
        start_date = candidates["entry_date"].min().date() if not candidates.empty else date(2020, 1, 1)
        end_date = candidates["entry_date"].max().date() + timedelta(days=100) # Buffer for exits
        
        n_rows = session.execute(
            select(MarketDataLake.trade_date, MarketDataLake.close_raw)
            .where(MarketDataLake.symbol == nifty_sym)
            .where(MarketDataLake.trade_date >= start_date)
            .where(MarketDataLake.trade_date <= end_date)
            .order_by(MarketDataLake.trade_date)
        ).all()
        
        trading_days = [r.trade_date for r in n_rows]
        nifty = pd.Series([float(r.close_raw) for r in n_rows], index=trading_days)

        # 2. Preload OHLCV for valid symbols to avoid N+1 queries
        valid_symbols = valid_df["symbol"].unique().tolist()
        p_rows = session.execute(
            select(MarketDataLake.symbol, MarketDataLake.trade_date, MarketDataLake.high_raw, MarketDataLake.low_raw, MarketDataLake.close_raw)
            .where(MarketDataLake.symbol.in_(valid_symbols))
            .where(MarketDataLake.trade_date >= start_date)
            .where(MarketDataLake.trade_date <= end_date)
        ).all()
        
        # prices[symbol][date] = (high, low, close)
        prices = {}
        for r in p_rows:
            if r.symbol not in prices:
                prices[r.symbol] = {}
            prices[r.symbol][r.trade_date] = (float(r.high_raw), float(r.low_raw), float(r.close_raw))

        # 3. Simulate day by day
        cash = initial_equity
        open_positions = []
        equity_history = []
        realized_rrs = []
        
        # We'll need slippage/STT params
        slip_pct = self.config.get("backtest", {}).get("pass_criteria", {}).get("estimated_slippage_pct", 0.1) / 100.0
        stt_pct = self.config.get("backtest", {}).get("pass_criteria", {}).get("estimated_stt_pct", 0.025) / 100.0

        for current_day in trading_days:
            # A. Update Exits
            surviving_positions = []
            for pos in open_positions:
                sym = pos["symbol"]
                if sym not in prices or current_day not in prices[sym]:
                    surviving_positions.append(pos)
                    continue
                
                high_val, low_val, close_val = prices[sym][current_day]
                pos["current_close"] = close_val
                
                # Check Stop Hit
                if low_val <= pos["live_stop"]:
                    exit_price = pos["live_stop"]
                    gross_val = exit_price * pos["shares"]
                    slippage = (pos["entry_price"] + exit_price) * pos["shares"] * slip_pct
                    stt = gross_val * stt_pct
                    
                    cash += (gross_val - slippage - stt)
                    
                    # Record realized RR
                    initial_risk = pos["entry_price"] - pos["initial_stop"]
                    if initial_risk > 0:
                        rr = (exit_price - pos["entry_price"]) / initial_risk
                        realized_rrs.append({"symbol": sym, "entry_date": pos["entry_date"], "realized_rr": rr})
                else:
                    # Update state
                    pos["days_held"] += 1
                    pos["highest_high"] = max(pos["highest_high"], high_val)
                    one_r = pos["entry_price"] - pos["initial_stop"]
                    
                    if pos["state"] == "INITIAL_RISK":
                        if pos["highest_high"] >= pos["entry_price"] + one_r:
                            pos["state"] = "RISK_FREE"
                            pos["live_stop"] = pos["entry_price"]
                        elif pos["days_held"] >= 15:
                            pos["state"] = "PENDING_MANUAL_EXIT"
                    elif pos["state"] == "RISK_FREE":
                        if pos["highest_high"] >= pos["target"]:
                            pos["state"] = "TRAILING"
                    elif pos["state"] == "TRAILING":
                        # Approx 1.5% trail
                        trail = pos["highest_high"] - (close_val * 0.015)
                        if trail > pos["live_stop"]:
                            pos["live_stop"] = trail
                            
                    surviving_positions.append(pos)
            
            open_positions = surviving_positions

            # B. Check Entries
            todays_entries = valid_df[valid_df["entry_date"].dt.date == current_day]
            for _, row in todays_entries.iterrows():
                cost = row["entry_price"] * row["shares"]
                if cash >= cost:
                    cash -= cost
                    open_positions.append({
                        "symbol": row["symbol"],
                        "entry_date": current_day,
                        "entry_price": row["entry_price"],
                        "shares": row["shares"],
                        "initial_stop": row["live_stop_loss"],
                        "live_stop": row["live_stop_loss"],
                        "target": row["initial_resistance_target"],
                        "state": "INITIAL_RISK",
                        "highest_high": row["entry_price"],
                        "days_held": 0,
                        "current_close": row["entry_price"]
                    })

            # C. Record Equity
            portfolio_val = cash + sum([p["shares"] * p["current_close"] for p in open_positions])
            equity_history.append(portfolio_val)

        equity = pd.Series(equity_history, index=trading_days)
        
        # Map RRs back to valid_df
        rr_df = pd.DataFrame(realized_rrs)
        if not rr_df.empty:
            rr_df["entry_date"] = pd.to_datetime(rr_df["entry_date"])
            valid_df = valid_df.merge(rr_df, on=["symbol", "entry_date"], how="left")
            valid_df["realized_rr"] = valid_df["realized_rr"].fillna(0.0)
        else:
            valid_df["realized_rr"] = 0.0

        # Max Drawdown
        roll_max = equity.cummax()
        drawdown = (equity - roll_max) / roll_max
        max_dd = abs(drawdown.min()) * 100

        # CAGR
        days = (equity.index[-1] - equity.index[0]).days
        years = days / 365.25 if days > 0 else 1
        cagr = ((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) * 100

        nifty_cagr = ((nifty.iloc[-1] / nifty.iloc[0]) ** (1 / years) - 1) * 100
        
        win_rate = 0.0
        if not valid_df.empty and "realized_rr" in valid_df.columns:
            wins = valid_df[valid_df["realized_rr"] > 0]
            win_rate = len(wins) / len(valid_df)

        metrics = {
            "max_drawdown_pct": max_dd,
            "cagr_pct": cagr,
            "nifty_cagr_pct": nifty_cagr,
            "alpha_pct": cagr - nifty_cagr,
            "sharpe": (cagr - 6.5) / (drawdown.std() * 100 * np.sqrt(252)) if drawdown.std() > 0 else 0,
            "total_trades": len(valid_df),
            "win_rate": win_rate
        }

        return {
            "equity_curve": equity,
            "trades_executed": valid_df,
            "trades_dropped": dropped_df,
            "summary": metrics
        }
