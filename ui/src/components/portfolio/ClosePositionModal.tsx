import React, { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { closePosition } from "../../api";
import { X, LogOut } from "lucide-react";

interface ClosePositionModalProps {
  position: any;
  onClose: () => void;
}

export default function ClosePositionModal({ position, onClose }: ClosePositionModalProps) {
  const queryClient = useQueryClient();
  const [exitPrice, setExitPrice] = useState<string>(position.entry_price ? position.entry_price.toString() : "");
  const [exitDate, setExitDate] = useState<string>(() => new Date().toISOString().split('T')[0]);
  const [exitReason, setExitReason] = useState<string>("MANUAL");

  const mutation = useMutation({
    mutationFn: closePosition,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      onClose();
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!exitPrice) return;
    
    mutation.mutate({
      position_id: position.id,
      exit_price: parseFloat(exitPrice),
      exit_date: exitDate,
      exit_reason: exitReason,
    });
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[#0f172a] border border-slate-700/80 rounded-2xl shadow-2xl max-w-md w-full overflow-hidden text-slate-100">
        <div className="flex justify-between items-center p-5 border-b border-slate-800">
          <div className="flex items-center space-x-2.5">
            <div className="p-2 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
              <LogOut className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Manual Exit Ticket: {position.symbol}</h3>
              <p className="text-[11px] text-slate-400 font-mono">Record Order Execution</p>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition">
            <X className="w-5 h-5" />
          </button>
        </div>
        
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div className="bg-slate-900 border border-slate-800 text-slate-300 text-xs p-3.5 rounded-xl flex justify-between font-mono">
            <div>
              <span className="text-slate-500 block text-[10px]">ENTRY PRICE</span>
              <span className="text-white font-bold text-sm">₹{position.entry_price?.toLocaleString("en-IN")}</span>
            </div>
            <div>
              <span className="text-slate-500 block text-[10px]">SHARES</span>
              <span className="text-cyan-400 font-bold text-sm">{position.shares}</span>
            </div>
            <div>
              <span className="text-slate-500 block text-[10px]">CURRENT STOP</span>
              <span className="text-rose-400 font-bold text-sm">₹{position.live_stop_loss?.toLocaleString("en-IN")}</span>
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1">Execution Exit Price (₹)</label>
            <input
              type="number"
              step="0.05"
              required
              value={exitPrice}
              onChange={(e) => setExitPrice(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-blue-500"
              placeholder="e.g. 1500.50"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1">Exit Date</label>
            <input
              type="date"
              required
              value={exitDate}
              onChange={(e) => setExitDate(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1">Exit Trigger / Strategy Reason</label>
            <select
              value={exitReason}
              onChange={(e) => setExitReason(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option value="MANUAL">Manual Discretionary Exit</option>
              <option value="STOP_HIT">Stop Loss Hit (2×ATR Trailing)</option>
              <option value="TIME_DECAY">Time Decay (15 Sessions to 1:1)</option>
              <option value="EARNINGS_EXIT">Pre-Earnings Risk Blackout</option>
              <option value="TARGET_HIT">Resistance Target Hit</option>
            </select>
          </div>
          
          <div className="pt-4 border-t border-slate-800 flex justify-end space-x-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium text-slate-300 hover:bg-slate-800 rounded-xl border border-slate-700 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="px-4 py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-500 rounded-xl transition shadow-lg shadow-blue-600/30 disabled:opacity-50"
            >
              {mutation.isPending ? "Recording Exit..." : "Record Exit in Ledger"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
