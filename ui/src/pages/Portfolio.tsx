import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchPortfolio, fetchLedgerSummary, type PortfolioSummary } from "../api";
import PositionTable from "../components/portfolio/PositionTable";
import ManageFundsPanel from "../components/portfolio/ManageFundsPanel";
import { AlertTriangle } from "lucide-react";
import clsx from "clsx";

export default function Portfolio() {
  const { data: portfolio, isLoading: portLoading } = useQuery({ 
    queryKey: ["portfolio"], 
    queryFn: fetchPortfolio 
  });
  const { data: ledger, isLoading: ledgerLoading } = useQuery({ 
    queryKey: ["ledger"], 
    queryFn: fetchLedgerSummary 
  });

  if (portLoading || ledgerLoading) {
    return (
      <div className="space-y-6">
        <div className="h-10 w-64 bg-slate-800 animate-pulse rounded-lg" />
        <div className="h-28 glass-card border border-slate-800 animate-pulse rounded-2xl" />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="h-24 glass-card border border-slate-800 animate-pulse rounded-xl" />
          <div className="h-24 glass-card border border-slate-800 animate-pulse rounded-xl" />
          <div className="h-24 glass-card border border-slate-800 animate-pulse rounded-xl" />
          <div className="h-24 glass-card border border-slate-800 animate-pulse rounded-xl" />
        </div>
      </div>
    );
  }

  const positions = portfolio?.positions || [];
  const summary: PortfolioSummary = portfolio?.summary || {};
  const liveEquity = ledger?.live_equity || 1000000;
  
  // Calculate invested capital and mark-to-market P&L
  let investedCapital = 0;
  let totalUnrealizedPnl = 0;
  
  positions.forEach((p: any) => {
    const cost = (p.entry_price || 0) * (p.shares || 0);
    const curr = (p.current_price || p.entry_price || 0) * (p.shares || 0);
    investedCapital += cost;
    totalUnrealizedPnl += (curr - cost);
  });

  const cashRemaining = Math.max(0, liveEquity - investedCapital);
  const cashPct = liveEquity > 0 ? (cashRemaining / liveEquity) * 100 : 100;
  const pnlPct = investedCapital > 0 ? (totalUnrealizedPnl / investedCapital) * 100 : 0.0;
  const isPnlPositive = totalUnrealizedPnl >= 0;

  const earningsAlerts = positions.filter((p: any) => p.earnings_alert);

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
            Active Portfolio & Trade Management
            <span className="text-xs font-normal font-mono px-2.5 py-1 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              Trailing Ratchet Guard
            </span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Live position tracking with 2×ATR trailing stops, earnings event surveillance, and 20-session time decay monitor.
          </p>
        </div>
      </div>

      {/* Account Equity & Funds Infusion Panel */}
      <ManageFundsPanel />

      {/* Corporate Action / Earnings Blackout Alert Banner */}
      {earningsAlerts.length > 0 && (
        <div className="glass-danger border border-amber-500/30 rounded-2xl p-4 flex items-start space-x-3.5">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <h4 className="font-bold text-amber-200 text-sm">
              Corporate Earnings Surveillance Alert ({earningsAlerts.length} Positions Affected)
            </h4>
            <div className="flex flex-wrap gap-2 pt-1">
              {earningsAlerts.map((pos: any) => (
                <span 
                  key={pos.id} 
                  className="px-2.5 py-1 rounded-lg bg-amber-500/20 text-amber-300 font-mono text-xs border border-amber-500/30"
                >
                  {pos.symbol}: Earnings announcement scheduled for {new Date(pos.next_earnings_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 4-Card Portfolio Metric Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
        <div className="glass-card border border-slate-800 rounded-xl p-4 font-mono">
          <span className="text-slate-400 text-xs uppercase tracking-wider block">Account Equity</span>
          <p className="text-xl font-bold text-white mt-1 tabular-nums">
            ₹{liveEquity.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
          </p>
          <span className="text-[11px] text-slate-400 block mt-0.5">Base Capital</span>
        </div>

        <div className="glass-card border border-slate-800 rounded-xl p-4 font-mono">
          <span className="text-slate-400 text-xs uppercase tracking-wider block">Invested Capital</span>
          <p className="text-xl font-bold text-white mt-1 tabular-nums">
            ₹{investedCapital.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
          </p>
          <span className="text-[11px] text-slate-400 block mt-0.5">
            {cashPct.toFixed(1)}% Liquid Cash
          </span>
        </div>

        <div className="glass-card border border-slate-800 rounded-xl p-4 font-mono">
          <span className="text-slate-400 text-xs uppercase tracking-wider block">Unrealized P&L</span>
          <p className={clsx("text-xl font-bold mt-1 tabular-nums", isPnlPositive ? "text-emerald-400" : "text-rose-400")}>
            {isPnlPositive ? "+" : ""}₹{totalUnrealizedPnl.toLocaleString("en-IN", { maximumFractionDigits: 0 })} ({isPnlPositive ? "+" : ""}{pnlPct.toFixed(2)}%)
          </p>
          <span className="text-[11px] text-slate-400 block mt-0.5">Mark to Market</span>
        </div>

        <div className="glass-card border border-slate-800 rounded-xl p-4 font-mono">
          <span className="text-slate-400 text-xs uppercase tracking-wider block">Open Risk Budget</span>
          <p className="text-xl font-bold text-slate-200 mt-1 tabular-nums">
            {(summary.total_risk_pct || 0).toFixed(1)}% / {(summary.max_risk_pct || 15).toFixed(1)}%
          </p>
          <span className="text-[11px] text-emerald-400 block mt-0.5">Max 1% per position</span>
        </div>
      </div>

      {/* Live Table */}
      <PositionTable positions={positions} />
    </div>
  );
}
