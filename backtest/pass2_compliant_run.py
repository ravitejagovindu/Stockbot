"""
FInsight Trading Engine — Pass 2 Compliant Run
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
import pandas as pd
import numpy as np
from sqlalchemy import select
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
        block_days = int(self.config.get("trade_management", {}).get("binary_event_block_days", 14))
        
        # Pillar 2: Pre-compute Nifty SMA if bull entry filter configured
        bull_sma_period = int(self.config.get("macro", {}).get("bull_entry_sma_period", 0))
        nifty_sma_map = {}
        nifty_close_map = {}
        if regime_name == "bull_run" and bull_sma_period > 0 and not candidates.empty:
            from data.db.models import MarketDataLake
            from engine_core.indicators import sma
            nifty_sym = self.config.get("data", {}).get("nifty_symbol", "NIFTY50_INDEX")
            c_start = candidates["entry_date"].min().date() - timedelta(days=120)
            c_end = candidates["entry_date"].max().date()
            n_rows = session.execute(
                select(MarketDataLake.trade_date, MarketDataLake.close_raw)
                .where(MarketDataLake.symbol == nifty_sym)
                .where(MarketDataLake.trade_date >= c_start)
                .where(MarketDataLake.trade_date <= c_end)
                .order_by(MarketDataLake.trade_date)
            ).all()
            if n_rows:
                n_df = pd.DataFrame(n_rows, columns=["trade_date", "close_raw"])
                n_df["close_raw"] = n_df["close_raw"].astype(float)
                n_df["sma"] = sma(n_df["close_raw"], bull_sma_period)
                nifty_sma_map = dict(zip(n_df["trade_date"], n_df["sma"]))
                nifty_close_map = dict(zip(n_df["trade_date"], n_df["close_raw"]))

        for _, trade in candidates.iterrows():
            sym = trade["symbol"]
            entry_date = trade["entry_date"].date()
            
            # Check Bull Regime 50-day SMA entry filter
            if regime_name == "bull_run" and bull_sma_period > 0:
                n_close = nifty_close_map.get(entry_date)
                n_sma = nifty_sma_map.get(entry_date)
                if n_close is not None and n_sma is not None and n_close < n_sma:
                    trade["drop_reason"] = f"BULL_NIFTY_BELOW_SMA{bull_sma_period}"
                    dropped_trades.append(trade)
                    continue

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

        # 2. Preload OHLCV for valid symbols and pre-compute exact Wilder's smoothed ATR(14)
        from engine_core.indicators import atr
        valid_symbols = valid_df["symbol"].unique().tolist()
        fetch_start_date = start_date - timedelta(days=60)  # 60 days buffer to warm up ATR(14)
        p_rows = session.execute(
            select(MarketDataLake.symbol, MarketDataLake.trade_date, MarketDataLake.high_raw, MarketDataLake.low_raw, MarketDataLake.close_raw)
            .where(MarketDataLake.symbol.in_(valid_symbols))
            .where(MarketDataLake.trade_date >= fetch_start_date)
            .where(MarketDataLake.trade_date <= end_date)
            .order_by(MarketDataLake.symbol, MarketDataLake.trade_date)
        ).all()
        
        # prices[symbol][date] = (high, low, close)
        # atrs[symbol][date] = exact ATR(14)
        prices = {}
        atrs = {}
        raw_records = []
        for r in p_rows:
            raw_records.append({
                "symbol": r.symbol,
                "trade_date": r.trade_date,
                "high": float(r.high_raw),
                "low": float(r.low_raw),
                "close": float(r.close_raw),
            })
            if r.symbol not in prices:
                prices[r.symbol] = {}
            prices[r.symbol][r.trade_date] = (float(r.high_raw), float(r.low_raw), float(r.close_raw))

        if raw_records:
            all_ohlcv_df = pd.DataFrame(raw_records)
            for sym, s_df in all_ohlcv_df.groupby("symbol"):
                s_df = s_df.sort_values("trade_date").reset_index(drop=True)
                s_df["atr14"] = atr(s_df["high"], s_df["low"], s_df["close"], period=14)
                atrs[sym] = {}
                for _, row in s_df.iterrows():
                    t_date = row["trade_date"]
                    # If atr14 is NaN during early warmup, fallback to 2.5% of close
                    atrs[sym][t_date] = float(row["atr14"]) if pd.notnull(row["atr14"]) else float(row["close"]) * 0.025

        # 3. Simulate day by day
        cash = initial_equity
        open_positions = []
        equity_history = []
        realized_rrs = []
        
        # We'll need slippage/STT params
        slip_pct = self.config.get("backtest", {}).get("pass_criteria", {}).get("estimated_slippage_pct", 0.1) / 100.0
        stt_pct = self.config.get("backtest", {}).get("pass_criteria", {}).get("estimated_stt_pct", 0.025) / 100.0
        
        time_decay_sessions = int(self.config.get("trade_management", {}).get("time_decay_sessions", 20))
        trail_mult_normal = float(self.config.get("risk", {}).get("trailing_stop_atr_multiplier", 2.5))
        trail_mult_ks = float(self.config.get("risk", {}).get("trailing_stop_atr_multiplier_kill_switch", 2.0))

        # Pre-fetch regime kill switch states
        from data.db.models import RegimeState as DBRegimeState
        r_rows = session.execute(
            select(DBRegimeState.eval_date, DBRegimeState.kill_switch_active)
            .where(DBRegimeState.eval_date >= start_date - timedelta(days=60))
            .where(DBRegimeState.eval_date <= end_date)
        ).all()
        regime_ks_map = {r.eval_date: r.kill_switch_active for r in r_rows}

        # Partial profit booking configuration
        partial_cfg = self.config.get("partial_profit", {})
        partial_enabled = bool(partial_cfg.get("enabled", False))
        partial_ladder = sorted(
            partial_cfg.get("exit_ladder", []),
            key=lambda x: float(x["rr_trigger"])
        )

        # Profit ratchet configuration
        ratchet_cfg = self.config.get("profit_ratchet", {})
        ratchet_enabled = bool(ratchet_cfg.get("enabled", False))
        enabled_regimes = ratchet_cfg.get("enabled_regimes")
        if enabled_regimes is not None and regime_name not in enabled_regimes:
            ratchet_enabled = False
        ratchet_rungs = sorted(
            ratchet_cfg.get("rungs", []),
            key=lambda x: float(x["trigger_rr"])
        )

        # Parabolic stop configuration
        parabolic_cfg = self.config.get("parabolic_stop", {})
        parabolic_enabled = bool(parabolic_cfg.get("enabled", False))
        parabolic_thresh_atr = float(parabolic_cfg.get("acceleration_threshold_atr", 3.0))
        parabolic_lookback = int(parabolic_cfg.get("acceleration_lookback_days", 5))
        parabolic_mult = float(parabolic_cfg.get("parabolic_atr_multiplier", 1.0))
        parabolic_trail_pct = parabolic_mult * 0.025

        for current_day in trading_days:
            is_ks_active = regime_ks_map.get(current_day, False)
            current_trail_mult = trail_mult_ks if is_ks_active else trail_mult_normal

            # A. Update Exits
            surviving_positions = []
            for pos in open_positions:
                sym = pos["symbol"]
                if sym not in prices or current_day not in prices[sym]:
                    surviving_positions.append(pos)
                    continue
                
                high_val, low_val, close_val = prices[sym][current_day]
                pos["current_close"] = close_val
                pos.setdefault("close_history", []).append(close_val)
                
                # Check Stop Hit OR Pending Manual Exit (simulate human closing the dead trade)
                if low_val <= pos["live_stop"] or pos["state"] == "PENDING_MANUAL_EXIT":
                    if pos["state"] == "PENDING_MANUAL_EXIT":
                        exit_price = close_val  # Human exits at EOD price
                    else:
                        exit_price = pos["live_stop"]
                        
                    shares_to_close = pos.get("shares_remaining", pos["shares"])
                    if shares_to_close > 0:
                        gross_val = exit_price * shares_to_close
                        slippage = (pos["entry_price"] + exit_price) * shares_to_close * slip_pct
                        stt = gross_val * stt_pct
                        cash += (gross_val - slippage - stt)
                        
                        initial_risk = pos["entry_price"] - pos["initial_stop"]
                        final_rr = (exit_price - pos["entry_price"]) / initial_risk if initial_risk > 0 else 0.0
                        pos.setdefault("realized_pieces", []).append((shares_to_close, final_rr))
                    
                    # Record blended realized RR
                    total_orig_shares = pos["shares"]
                    pieces = pos.get("realized_pieces", [])
                    blended_rr = (
                        sum(s * r for s, r in pieces) / total_orig_shares
                        if total_orig_shares > 0 and pieces else 0.0
                    )
                    realized_rrs.append({"symbol": sym, "entry_date": pos["entry_date"], "realized_rr": blended_rr})
                else:
                    # Update state
                    pos["days_held"] += 1
                    pos["highest_high"] = max(pos["highest_high"], high_val)
                    one_r = pos["entry_price"] - pos["initial_stop"]
                    
                    # Check partial profit ladder
                    if partial_enabled and partial_ladder and one_r > 0:
                        current_rr = (high_val - pos["entry_price"]) / one_r
                        for rung in partial_ladder:
                            trigger = float(rung["rr_trigger"])
                            if trigger > pos.get("last_partial_rr", 0.0) and current_rr >= trigger:
                                exit_pct = float(rung["exit_pct"])
                                shares_rem = pos.get("shares_remaining", pos["shares"])
                                shares_to_exit = int(np.floor(shares_rem * (exit_pct / 100.0)))
                                
                                if 0 < shares_to_exit < shares_rem:
                                    p_exit_price = pos["entry_price"] + (trigger * one_r)
                                    p_gross = p_exit_price * shares_to_exit
                                    p_slip = (pos["entry_price"] + p_exit_price) * shares_to_exit * slip_pct
                                    p_stt = p_gross * stt_pct
                                    cash += (p_gross - p_slip - p_stt)
                                    
                                    pos["shares_remaining"] = shares_rem - shares_to_exit
                                    pos["last_partial_rr"] = trigger
                                    pos.setdefault("realized_pieces", []).append((shares_to_exit, trigger))
                                    break
                    
                    if pos["state"] == "INITIAL_RISK":
                        if pos["highest_high"] >= pos["entry_price"] + one_r:
                            pos["state"] = "RISK_FREE"
                            pos["live_stop"] = pos["entry_price"]
                        elif pos["days_held"] >= time_decay_sessions:
                            pos["state"] = "PENDING_MANUAL_EXIT"
                    elif pos["state"] == "RISK_FREE":
                        if pos["highest_high"] >= pos["target"]:
                            pos["state"] = "TRAILING"

                    current_atr = atrs.get(sym, {}).get(current_day, close_val * 0.025)

                    if pos["state"] == "TRAILING":
                        # Check for parabolic acceleration
                        hist = pos.get("close_history", [])
                        if parabolic_enabled and len(hist) >= 2 and current_atr > 0:
                            lb = min(parabolic_lookback, len(hist))
                            net_move = close_val - hist[-lb]
                            if net_move >= (parabolic_thresh_atr * current_atr):
                                pos["state"] = "PARABOLIC_TRAILING"

                        if pos["state"] == "TRAILING":
                            # Standard ATR trail (Highest High - multiplier × exact ATR14)
                            trail = pos["highest_high"] - (current_trail_mult * current_atr)
                            if trail > pos["live_stop"]:
                                pos["live_stop"] = trail

                    if pos["state"] == "PARABOLIC_TRAILING":
                        # Tightened parabolic ATR trail (Highest High - multiplier × exact ATR14)
                        trail = pos["highest_high"] - (parabolic_mult * current_atr)
                        if trail > pos["live_stop"]:
                            pos["live_stop"] = trail

                    # Apply Step-Lock Profit Ratchet floor across active states
                    if ratchet_enabled and one_r > 0 and pos["state"] != "PENDING_MANUAL_EXIT":
                        highest_rr = (pos["highest_high"] - pos["entry_price"]) / one_r
                        for rung in ratchet_rungs:
                            if highest_rr >= float(rung["trigger_rr"]):
                                ratchet_stop = pos["entry_price"] + (float(rung["lock_rr"]) * one_r)
                                if ratchet_stop > pos["live_stop"]:
                                    pos["live_stop"] = ratchet_stop
                            
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
                        "shares_remaining": row["shares"],
                        "initial_stop": row["live_stop_loss"],
                        "live_stop": row["live_stop_loss"],
                        "target": row["initial_resistance_target"],
                        "state": "INITIAL_RISK",
                        "highest_high": row["entry_price"],
                        "days_held": 0,
                        "current_close": row["entry_price"],
                        "last_partial_rr": 0.0,
                        "realized_pieces": [],
                        "close_history": [row["entry_price"]],
                    })

            # C. Record Equity
            portfolio_val = cash + sum([p.get("shares_remaining", p["shares"]) * p["current_close"] for p in open_positions])
            equity_history.append(portfolio_val)

        # Record blended RR for any positions left open at end of trading period
        for pos in open_positions:
            shares_to_close = pos.get("shares_remaining", pos["shares"])
            if shares_to_close > 0:
                one_r = pos["entry_price"] - pos["initial_stop"]
                final_rr = (pos["current_close"] - pos["entry_price"]) / one_r if one_r > 0 else 0.0
                pos.setdefault("realized_pieces", []).append((shares_to_close, final_rr))
            total_orig_shares = pos["shares"]
            pieces = pos.get("realized_pieces", [])
            blended_rr = (
                sum(s * r for s, r in pieces) / total_orig_shares
                if total_orig_shares > 0 and pieces else 0.0
            )
            realized_rrs.append({"symbol": pos["symbol"], "entry_date": pos["entry_date"], "realized_rr": blended_rr})

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
