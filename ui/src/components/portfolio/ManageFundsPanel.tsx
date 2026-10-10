import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchLedgerSummary, depositFunds, withdrawFunds } from "../../api";

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

  if (isLoading) return <div className="h-20 bg-gray-50 rounded animate-pulse"></div>;

  const handleConfirm = () => {
    const val = parseFloat(amount);
    if (!val || val <= 0) return alert("Enter a valid amount > 0");
    if (showModal === "DEPOSIT") {
      depositMut.mutate({ amount: val, notes });
    } else if (showModal === "WITHDRAW") {
      withdrawMut.mutate({ amount: val, notes });
    }
  };

  return (
    <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200 flex flex-col md:flex-row items-center justify-between">
      <div>
        <h4 className="text-gray-500 font-medium text-sm">Account Equity</h4>
        <div className="flex items-baseline space-x-2">
          <span className="text-3xl font-bold text-gray-900">₹{ledger?.live_equity.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
          {ledger?.fallback_used && (
            <span className="text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
              Using .env default
            </span>
          )}
        </div>
      </div>
      
      <div className="flex space-x-3 mt-4 md:mt-0">
        <button 
          onClick={() => setShowModal("DEPOSIT")}
          className="px-4 py-2 bg-green-50 text-green-700 hover:bg-green-100 font-medium rounded-md transition border border-green-200"
        >
          Deposit
        </button>
        <button 
          onClick={() => setShowModal("WITHDRAW")}
          className="px-4 py-2 bg-red-50 text-red-700 hover:bg-red-100 font-medium rounded-md transition border border-red-200"
        >
          Withdraw
        </button>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
            <h3 className="text-lg font-bold mb-4">{showModal === "DEPOSIT" ? "Deposit Funds" : "Withdraw Funds"}</h3>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Amount (₹)</label>
                <input 
                  type="number" 
                  value={amount}
                  onChange={e => setAmount(e.target.value)}
                  className="w-full border-gray-300 rounded-md shadow-sm p-2 border focus:ring-blue-500 focus:border-blue-500" 
                  placeholder="25000"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Notes (Optional)</label>
                <input 
                  type="text" 
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                  className="w-full border-gray-300 rounded-md shadow-sm p-2 border focus:ring-blue-500 focus:border-blue-500" 
                  placeholder="e.g. Oct SIP"
                />
              </div>
            </div>

            <div className="mt-6 flex justify-end space-x-3">
              <button 
                onClick={() => setShowModal(null)}
                className="px-4 py-2 border rounded text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button 
                onClick={handleConfirm}
                disabled={depositMut.isPending || withdrawMut.isPending}
                className={`px-4 py-2 rounded text-white ${showModal === "DEPOSIT" ? "bg-green-600 hover:bg-green-700" : "bg-red-600 hover:bg-red-700"}`}
              >
                Confirm {showModal}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
