import React, { useState } from "react";
import { Copy, Check } from "lucide-react";
import clsx from "clsx";

export default function TradeTicketCard({ setup }: { setup: any }) {
  const [copied, setCopied] = useState(false);
  const isGreen = setup.projected_rr >= 1.5;

  const handleCopy = () => {
    const text = `TRADE ORDER TICKET:\nSymbol: ${setup.symbol}\nExchange: NSE (Cash)\nOrder Type: LIMIT BUY\nLimit Price: ₹${setup.entry_price}\nSL Trigger: ₹${setup.live_stop_loss}\nQuantity: ${setup.shares} shares\nRisk: 1.0% (₹${setup.risk_amount ? setup.risk_amount.toLocaleString("en-IN") : "10,000"})`;
    
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    }
  };

  const stopPct = setup.entry_price > 0 && setup.live_stop_loss > 0
    ? (((setup.live_stop_loss - setup.entry_price) / setup.entry_price) * 100).toFixed(2)
    : "-3.00";

  return (
    <div className="glass-card border border-slate-700/80 rounded-2xl p-6 space-y-5 hover:border-blue-500/40 transition duration-300 flex flex-col justify-between">
      {/* Header */}
      <div>
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-xl font-bold text-white font-mono">{setup.symbol}</span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                NSE: CASH
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              {setup.sector || "General Industrials"} • Donchian 20d Breakout
            </p>
          </div>
          <span
            className={clsx(
              "text-xs font-mono font-bold px-2.5 py-1 rounded-lg border",
              isGreen
                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                : "bg-amber-500/10 text-amber-300 border-amber-500/20"
            )}
          >
            R:R 1 : {setup.projected_rr ? setup.projected_rr.toFixed(2) : "1.50"}
          </span>
        </div>

        {/* Ticket Specification Grid */}
        <div className="grid grid-cols-2 gap-3 p-4 rounded-xl bg-slate-900/80 border border-slate-800 text-xs font-mono mt-4">
          <div>
            <span className="text-slate-400 text-[11px] block">Entry Trigger (Limit)</span>
            <span className="text-white font-bold text-sm">
              ₹{setup.entry_price ? setup.entry_price.toLocaleString("en-IN") : "0"}
            </span>
          </div>

          <div>
            <span className="text-slate-400 text-[11px] block">Hard Stop Loss</span>
            <span className="text-rose-400 font-bold text-sm flex items-center gap-1">
              ₹{setup.live_stop_loss ? setup.live_stop_loss.toLocaleString("en-IN") : "0"}
              <span className="text-[10px] text-rose-300 font-normal">({stopPct}%)</span>
            </span>
          </div>

          <div>
            <span className="text-slate-400 text-[11px] block">Quantity (1% Risk)</span>
            <span className="text-cyan-400 font-bold text-sm">
              {setup.shares || 0} Shares
            </span>
          </div>

          <div>
            <span className="text-slate-400 text-[11px] block">Order Capital</span>
            <span className="text-slate-200 font-bold text-sm">
              ₹{setup.position_value ? setup.position_value.toLocaleString("en-IN") : "0"}
            </span>
          </div>
        </div>
      </div>

      {/* Execution Footer & Copy Action */}
      <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between">
        <span className="text-[11px] text-slate-400">
          Stop formula: {setup.active_stop || "Max(Donchian Low, Entry - 1.5×ATR)"}
        </span>
        <button
          onClick={handleCopy}
          className={clsx(
            "px-3.5 py-2 text-xs font-semibold rounded-xl border transition flex items-center gap-1.5 cursor-pointer",
            copied
              ? "bg-emerald-600/20 text-emerald-300 border-emerald-500/40"
              : "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700"
          )}
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span>Ticket Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5 text-slate-400" />
              <span>Copy Order Ticket</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}
