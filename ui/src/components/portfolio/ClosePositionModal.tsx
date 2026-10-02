import React, { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { closePosition } from "../../api";
import { X } from "lucide-react";

interface ClosePositionModalProps {
  position: any;
  onClose: () => void;
}

export default function ClosePositionModal({ position, onClose }: ClosePositionModalProps) {
  const queryClient = useQueryClient();
  const [exitPrice, setExitPrice] = useState<string>("");
  const [exitDate, setExitDate] = useState<string>(new Date().toISOString().split('T')[0]);
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full overflow-hidden">
        <div className="flex justify-between items-center p-5 border-b border-gray-100">
          <h3 className="text-xl font-bold text-gray-900">Close Position: {position.symbol}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div className="bg-blue-50 text-blue-800 text-sm p-3 rounded-lg flex justify-between">
            <span>Entry Price: ₹{position.entry_price.toLocaleString("en-IN")}</span>
            <span>Shares: {position.shares}</span>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Exit Price (₹)</label>
            <input
              type="number"
              step="0.05"
              required
              value={exitPrice}
              onChange={(e) => setExitPrice(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="e.g. 1500.50"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Exit Date</label>
            <input
              type="date"
              required
              value={exitDate}
              onChange={(e) => setExitDate(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Exit Reason</label>
            <select
              value={exitReason}
              onChange={(e) => setExitReason(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
            >
              <option value="MANUAL">Manual Exit (Discretionary)</option>
              <option value="STOP_HIT">Stop Loss Hit</option>
              <option value="TIME_DECAY">Time Decay (15 days)</option>
              <option value="EARNINGS_EXIT">Earnings Alert Exit</option>
              <option value="OTHER">Other</option>
            </select>
          </div>
          
          <div className="pt-4 border-t border-gray-100 flex justify-end space-x-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 rounded-md transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors disabled:opacity-50"
            >
              {mutation.isPending ? "Closing..." : "Confirm Exit"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
