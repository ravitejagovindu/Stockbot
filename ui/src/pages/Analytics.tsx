import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAnalytics } from "../api";
import DecayIndicator from "../components/analytics/DecayIndicator";
import RRScatterPlot from "../components/analytics/RRScatterPlot";
import { FolderArchive } from "lucide-react";
import clsx from "clsx";

export default function Analytics() {
  const { data: analytics, isLoading } = useQuery({ 
    queryKey: ["analytics"], 
    queryFn: () => fetchAnalytics(200) 
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="h-10 w-64 bg-slate-800 animate-pulse rounded-lg" />
        <div className="h-28 glass-card border border-slate-800 animate-pulse rounded-2xl" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="h-24 glass-card border border-slate-800 animate-pulse rounded-xl" />
          <div className="h-24 glass-card border border-slate-800 animate-pulse rounded-xl" />
          <div className="h-24 glass-card border border-slate-800 animate-pulse rounded-xl" />
          <div className="h-24 glass-card border border-slate-800 animate-pulse rounded-xl" />
        </div>
      </div>
    );
  }

  const { summary = {}, trades = [] } = analytics || {};
  const totalTrades = summary.total_trades || trades.length || 0;
  const winRate = summary.win_rate !== undefined ? (summary.win_rate * 100).toFixed(1) : "0.0";
  const avgProjRr = summary.avg_projected_rr ? summary.avg_projected_rr.toFixed(2) : "1.50";
  const avgRealRr = summary.avg_realized_rr ? summary.avg_realized_rr.toFixed(2) : "0.00";

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
            Quant Diagnostics & Strategy Decay Monitor
            <span className="text-xs font-normal font-mono px-2.5 py-1 rounded-md bg-blue-500/10 text-blue-400 border border-blue-500/20">
              Alpha Health Monitor
            </span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Tracks live execution slippage, rolling win rates, and early warnings for edge degradation.
          </p>
        </div>
      </div>

      {/* Model Robustness & Strategy Decay Scorecard */}
      <DecayIndicator summary={summary} />

      {/* 4-Card KPI Metric Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="glass-card border border-slate-800 rounded-xl p-4 font-mono">
          <span className="text-slate-400 text-xs uppercase tracking-wider block">Total Closed Trades</span>
          <p className="text-2xl font-extrabold text-white mt-1 tabular-nums">
            {totalTrades}
          </p>
          <span className="text-[11px] text-slate-400 block mt-0.5">Since inception</span>
        </div>

        <div className="glass-card border border-slate-800 rounded-xl p-4 font-mono">
          <span className="text-slate-400 text-xs uppercase tracking-wider block">Win Rate</span>
          <p className={clsx("text-2xl font-extrabold mt-1 tabular-nums", parseFloat(winRate) >= 50 ? "text-emerald-400" : "text-white")}>
            {winRate}%
          </p>
          <span className="text-[11px] text-slate-400 block mt-0.5">Target: &gt;50%</span>
        </div>

        <div className="glass-card border border-slate-800 rounded-xl p-4 font-mono">
          <span className="text-slate-400 text-xs uppercase tracking-wider block">Avg Proj R:R</span>
          <p className="text-2xl font-extrabold text-white mt-1 tabular-nums">
            {avgProjRr} R
          </p>
          <span className="text-[11px] text-slate-400 block mt-0.5">Entry criteria</span>
        </div>

        <div className="glass-card border border-slate-800 rounded-xl p-4 font-mono">
          <span className="text-slate-400 text-xs uppercase tracking-wider block">Realized Expectancy</span>
          <p className={clsx("text-2xl font-extrabold mt-1 tabular-nums", parseFloat(avgRealRr) > 0 ? "text-emerald-400" : "text-white")}>
            {parseFloat(avgRealRr) > 0 ? "+" : ""}{avgRealRr} R
          </p>
          <span className="text-[11px] text-slate-400 block mt-0.5">Per trade average</span>
        </div>
      </div>

      {/* R:R Parity Scatter Plot */}
      <RRScatterPlot trades={trades} />

      {/* Recent Closed Trades Table */}
      <div className="glass-card border border-slate-800 rounded-2xl overflow-hidden mt-8">
        <div className="p-5 border-b border-slate-800/80 flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-white">Recent Closed Trades</h3>
            <p className="text-xs text-slate-400">Chronological audit ledger of realized trade exits.</p>
          </div>
          <span className="text-xs font-mono px-2.5 py-1 rounded bg-slate-800 text-slate-300 border border-slate-700">
            {trades.length} Records Logged
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 text-[11px] font-mono uppercase text-slate-400 bg-slate-950/40">
                <th className="py-3 px-4">Symbol</th>
                <th className="py-3 px-4">Exit Date</th>
                <th className="py-3 px-4 text-right">Entry Price</th>
                <th className="py-3 px-4 text-right">Exit Price</th>
                <th className="py-3 px-4 text-right">Realized R:R</th>
                <th className="py-3 px-4 text-center">Exit Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-xs">
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    <div className="flex flex-col items-center justify-center space-y-2">
                      <FolderArchive className="w-8 h-8 text-slate-500 mb-1" />
                      <p className="font-semibold text-slate-200 text-sm">No closed trades logged yet</p>
                      <p className="text-xs text-slate-400">
                        Once live positions hit profit targets, trailing stops, or decay limits, they appear here.
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                trades.map((t: any, idx: number) => {
                  const isPositive = (t.realized_rr || 0) >= 1.0;
                  const isBreakEven = (t.realized_rr || 0) > 0 && (t.realized_rr || 0) < 1.0;

                  return (
                    <tr key={t.id || idx} className="hover:bg-slate-800/30 transition">
                      <td className="py-3.5 px-4 font-bold text-white font-mono">
                        {t.symbol}
                      </td>
                      <td className="py-3.5 px-4 font-mono text-slate-400">
                        {new Date(t.exit_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}
                      </td>
                      <td className="py-3.5 px-4 font-mono text-slate-300 text-right">
                        ₹{t.entry_price ? t.entry_price.toLocaleString("en-IN") : "0"}
                      </td>
                      <td className="py-3.5 px-4 font-mono text-slate-300 text-right font-medium">
                        ₹{t.exit_price ? t.exit_price.toLocaleString("en-IN") : "0"}
                      </td>
                      <td className="py-3.5 px-4 text-right font-mono">
                        <span
                          className={clsx(
                            "px-2 py-0.5 rounded text-xs font-bold border",
                            isPositive
                              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                              : isBreakEven
                              ? "bg-amber-500/10 text-amber-300 border-amber-500/20"
                              : "bg-rose-500/10 text-rose-400 border-rose-500/20"
                          )}
                        >
                          {t.realized_rr ? `${(t.realized_rr > 0 ? "+" : "")}${t.realized_rr.toFixed(2)} R` : "0.00 R"}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-center font-mono">
                        <span className="text-[11px] text-slate-400 uppercase tracking-wider bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
                          {t.exit_reason ? t.exit_reason.replace(/_/g, " ") : "MANUAL"}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
