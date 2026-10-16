import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchLedgerSummary, depositFunds, withdrawFunds } from "../../api";
import { ArrowDownRight, ArrowUpRight, Wallet, X } from "lucide-react";
import clsx from "clsx";

export default function ManageFundsPanel() {
  const queryClient = useQueryClient();
  const { data: ledger, isLoading } = useQuery({ queryKey: ["ledger"], queryFn: fetchLedgerSummary });
  
  const [showModal, setShowModal] = useState<"DEPOSIT" | "WITHDRAW" | null>(null);
  const [amount, setAmount] = useState("");
  const [notes, setNotes] = useState("");

  const depositMut = useMutation({
    mutationFn: depositFunds,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ledger"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      setShowModal(null);
      setAmount("");
      setNotes("");
    }
  });

  const withdrawMut = useMutation({
    mutationFn: withdrawFunds,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ledger"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      setShowModal(null);
      setAmount("");
      setNotes("");
    }
  });

  if (isLoading) {
    return <div className="h-24 glass-card border border-slate-800 rounded-2xl animate-pulse" />;
  }

  const handleConfirm = () => {
    const val = parseFloat(amount);
    if (!val || val <= 0) return alert("Enter a valid amount > 0");
    if (showModal === "DEPOSIT") {
      depositMut.mutate({ amount: val, notes });
    } else if (showModal === "WITHDRAW") {
      withdrawMut.mutate({ amount: val, notes });
    }
  };

  const liveEquity = ledger?.live_equity || 1000000;

  return (
    <div className="glass-card border border-slate-800 rounded-2xl p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
      <div>
        <div className="flex items-center space-x-2">
          <Wallet className="w-4 h-4 text-blue-400" />
          <h4 className="text-slate-400 font-semibold text-xs uppercase font-mono tracking-wider">
            Total Account Equity
          </h4>
        </div>
        <div className="flex items-baseline space-x-3 mt-1.5">
          <span className="text-3xl font-extrabold text-white font-mono tabular-nums tracking-tight">
            ₹{liveEquity.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
          </span>
          {ledger?.fallback_used ? (
            <span className="text-[11px] font-mono text-cyan-300 bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/20">
              Simulated Base Balance
            </span>
          ) : (
            <span className="text-[11px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
              Live Ledger Verified
            </span>
          )}
        </div>
        <p className="text-xs text-slate-400 mt-1">
          Base capital used to compute 1.0% maximum risk allocation per trade ticket.
        </p>
      </div>
      
      <div className="flex items-center space-x-3">
        <button 
          onClick={() => setShowModal("DEPOSIT")}
          className="px-4 py-2 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 font-medium text-xs rounded-xl transition border border-emerald-500/30 flex items-center gap-1.5 cursor-pointer"
        >
          <ArrowDownRight className="w-3.5 h-3.5 text-emerald-400" />
          Deposit Funds
        </button>
        <button 
          onClick={() => setShowModal("WITHDRAW")}
          className="px-4 py-2 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20 font-medium text-xs rounded-xl transition border border-rose-500/30 flex items-center gap-1.5 cursor-pointer"
        >
          <ArrowUpRight className="w-3.5 h-3.5 text-rose-400" />
          Withdraw Funds
        </button>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#0f172a] border border-slate-700/80 rounded-2xl shadow-2xl w-full max-w-md p-6 text-slate-100">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Wallet className="w-4 h-4 text-blue-400" />
                <span>{showModal === "DEPOSIT" ? "Deposit Capital" : "Withdraw Capital"}</span>
              </h3>
              <button 
                onClick={() => setShowModal(null)} 
                className="text-slate-400 hover:text-white transition"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            
            <div className="space-y-4 pt-4">
              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1">Amount (₹)</label>
                <input 
                  type="number" 
                  value={amount}
                  onChange={e => setAmount(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-blue-500" 
                  placeholder="25000"
                  autoFocus
                />
              </div>
              
              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1">Notes / Reference (Optional)</label>
                <input 
                  type="text" 
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500" 
                  placeholder="e.g. Monthly SIP Infusion"
                />
              </div>
            </div>

            <div className="mt-6 flex justify-end space-x-3 pt-3 border-t border-slate-800">
              <button 
                onClick={() => setShowModal(null)}
                className="px-4 py-2 border border-slate-700 rounded-xl text-xs font-medium text-slate-300 hover:bg-slate-800 transition"
              >
                Cancel
              </button>
              <button 
                onClick={handleConfirm}
                disabled={depositMut.isPending || withdrawMut.isPending}
                className={clsx(
                  "px-4 py-2 rounded-xl text-xs font-semibold text-white shadow-lg transition disabled:opacity-50",
                  showModal === "DEPOSIT" 
                    ? "bg-emerald-600 hover:bg-emerald-500" 
                    : "bg-rose-600 hover:bg-rose-500"
                )}
              >
                {depositMut.isPending || withdrawMut.isPending ? "Processing..." : `Confirm ${showModal}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
