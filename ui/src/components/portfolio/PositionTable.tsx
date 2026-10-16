import React, { useState } from "react";
import clsx from "clsx";
import ClosePositionModal from "./ClosePositionModal";
import { AlertTriangle, FolderArchive } from "lucide-react";

export default function PositionTable({ positions = [] }: { positions: any[] }) {
  const [closingPos, setClosingPos] = useState<any | null>(null);

  const getStateBadge = (state: string) => {
    switch (state) {
      case "INITIAL_RISK":
        return <span className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono text-[11px]">Initial Risk</span>;
      case "RISK_FREE_1_TO_1":
        return <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono text-[11px]">1:1 Breakeven</span>;
      case "TRAILING_ATR":
        return <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 font-mono text-[11px]">2×ATR Trailing</span>;
      case "PARABOLIC_TRAILING":
        return <span className="px-2 py-0.5 rounded bg-purple-500/10 text-purple-300 border border-purple-500/20 font-mono text-[11px]">Parabolic 🚀</span>;
      case "PENDING_MANUAL_EXIT":
        return <span className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30 font-mono text-[11px] animate-pulse">Pending Exit</span>;
      default:
        return <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700 font-mono text-[11px]">{state}</span>;
    }
  };

  const getDaysHeldDisplay = (pos: any) => {
    const days = pos.days_held || 0;
    const maxDays = 15;
    const pct = Math.min(100, (days / maxDays) * 100);
    const isTargetHit = pos.position_state !== "INITIAL_RISK";

    return (
      <div className="space-y-1 w-28 font-mono">
        <div className="flex justify-between text-[11px]">
          <span className="text-slate-300">Day {days} / {maxDays}</span>
          {isTargetHit ? (
            <span className="text-emerald-400 text-[10px]">&gt; 1:1 Hit</span>
          ) : (
            <span className={clsx("text-[10px]", days >= 12 ? "text-rose-400" : "text-slate-400")}>
              {maxDays - days}d left
            </span>
          )}
        </div>
        <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
          <div
            className={clsx(
              "h-1.5 rounded-full transition-all",
              isTargetHit ? "bg-emerald-400" : days >= 12 ? "bg-rose-500" : "bg-blue-500"
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    );
  };

  return (
    <div className="glass-card border border-slate-800 rounded-2xl overflow-hidden">
      <div className="p-5 border-b border-slate-800/80 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Live Monitored Positions</h3>
          <p className="text-xs text-slate-400">Positions actively managed under 2×ATR ratchet trailing stops.</p>
        </div>
        <span className="text-xs font-mono px-2.5 py-1 rounded bg-slate-800 text-slate-300 border border-slate-700">
          {positions.length} Positions Active
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-800 text-[11px] font-mono uppercase text-slate-400 bg-slate-950/40">
              <th className="py-3 px-4">Symbol / Entry</th>
              <th className="py-3 px-4">Entry / Current Price</th>
              <th className="py-3 px-4">Stop Loss (Ratchet)</th>
              <th className="py-3 px-4">Unrealized P&L</th>
              <th className="py-3 px-4">State</th>
              <th className="py-3 px-4">Time Decay (15d)</th>
              <th className="py-3 px-4">Surveillance Alert</th>
              <th className="py-3 px-4 text-right">Manual Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 text-xs">
            {positions.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-12 text-center text-slate-400">
                  <div className="flex flex-col items-center justify-center space-y-2">
                    <FolderArchive className="w-8 h-8 text-slate-500 mb-1" />
                    <p className="font-semibold text-slate-200 text-sm">No open positions found</p>
                    <p className="text-xs text-slate-400">
                      All capital safely preserved in liquid cash while macro kill switch is active.
                    </p>
                  </div>
                </td>
              </tr>
            ) : (
              positions.map((pos) => {
                const isProfitLocked = pos.live_stop_loss > pos.initial_stop_loss;
                const currentPrice = pos.current_price || pos.entry_price;
                const pnl = (currentPrice - pos.entry_price) * (pos.shares || 1);
                const pnlPct = pos.entry_price > 0 ? ((currentPrice - pos.entry_price) / pos.entry_price) * 100 : 0;
                const isPositive = pnl >= 0;

                return (
                  <tr
                    key={pos.id}
                    className={clsx(
                      "hover:bg-slate-800/30 transition",
                      pos.position_state === "PENDING_MANUAL_EXIT" && "bg-rose-500/5"
                    )}
                  >
                    {/* Symbol / Entry */}
                    <td className="py-4 px-4">
                      <span className="font-bold text-white font-mono text-sm block">{pos.symbol}</span>
                      <span className="text-[11px] text-slate-400 font-mono">
                        {pos.sector} • {new Date(pos.entry_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}
                      </span>
                    </td>

                    {/* Entry / Current Price */}
                    <td className="py-4 px-4 font-mono">
                      <span className="text-slate-400 block text-[11px]">
                        Entry: ₹{pos.entry_price ? pos.entry_price.toLocaleString("en-IN") : "0"}
                      </span>
                      <span className="text-white font-bold">
                        LTP: ₹{currentPrice.toLocaleString("en-IN")}
                      </span>
                    </td>

                    {/* Stop Loss & Ratchet */}
                    <td className="py-4 px-4 font-mono">
                      <span className={clsx("font-bold block", isProfitLocked ? "text-emerald-400" : "text-rose-400")}>
                        ₹{pos.live_stop_loss ? pos.live_stop_loss.toLocaleString("en-IN") : "0"}
                      </span>
                      {isProfitLocked ? (
                        <span className="text-[10px] text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded px-1.5 py-0.5 inline-block mt-0.5 font-medium">
                          ✓ Locked Profit
                        </span>
                      ) : (
                        <span className="text-[10px] text-slate-400 block mt-0.5">
                          Initial Stop
                        </span>
                      )}
                    </td>

                    {/* Unrealized P&L */}
                    <td className="py-4 px-4 font-mono">
                      <span className={clsx("font-bold text-sm block", isPositive ? "text-emerald-400" : "text-rose-400")}>
                        {isPositive ? "+" : ""}₹{pnl.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                      </span>
                      <span className={clsx("text-[10px] block mt-0.5", isPositive ? "text-emerald-400" : "text-rose-400")}>
                        {isPositive ? "+" : ""}{pnlPct.toFixed(2)}%
                      </span>
                    </td>

                    {/* State */}
                    <td className="py-4 px-4">
                      {getStateBadge(pos.position_state)}
                    </td>

                    {/* Time Decay */}
                    <td className="py-4 px-4">
                      {getDaysHeldDisplay(pos)}
                    </td>

                    {/* Surveillance Alert */}
                    <td className="py-4 px-4">
                      {pos.earnings_alert ? (
                        <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 font-mono text-[11px] flex items-center gap-1 w-fit">
                          <AlertTriangle className="w-3 h-3 text-amber-400" />
                          <span>Earnings in {pos.next_earnings_date ? new Date(pos.next_earnings_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }) : "Soon"}</span>
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono text-[11px]">
                          Clean (&gt;30d)
                        </span>
                      )}
                    </td>

                    {/* Action */}
                    <td className="py-4 px-4 text-right">
                      <button
                        onClick={() => setClosingPos(pos)}
                        className="px-3 py-1.5 text-xs font-semibold rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition cursor-pointer"
                      >
                        Exit Ticket
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {closingPos && (
        <ClosePositionModal position={closingPos} onClose={() => setClosingPos(null)} />
      )}
    </div>
  );
}
