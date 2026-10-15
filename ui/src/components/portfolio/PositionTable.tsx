import React, { useState } from "react";
import clsx from "clsx";
import ClosePositionModal from "./ClosePositionModal";

export default function PositionTable({ positions }: { positions: any[] }) {
  const [closingPos, setClosingPos] = useState<any | null>(null);

  const getStateColor = (state: string) => {
    switch (state) {
      case "INITIAL_RISK": return "bg-blue-100 text-blue-800 border-blue-200";
      case "RISK_FREE_1_TO_1": return "bg-green-100 text-green-800 border-green-200";
      case "TRAILING_ATR": return "bg-amber-100 text-amber-800 border-amber-200";
      case "PARABOLIC_TRAILING": return "bg-purple-100 text-purple-800 border-purple-200";
      case "PENDING_MANUAL_EXIT": return "bg-red-100 text-red-800 border-red-300 animate-pulse";
      default: return "bg-gray-100 text-gray-800";
    }
  };

  const getDaysHeldDisplay = (pos: any) => {
    if (pos.position_state === "INITIAL_RISK") {
      const pct = Math.min(100, (pos.days_held / 15) * 100);
      return (
        <div className="flex flex-col space-y-1 w-24">
          <span className="text-xs text-gray-500">{pos.days_held}/15 days</span>
          <div className="w-full bg-gray-200 rounded-full h-1.5">
            <div className={clsx("h-1.5 rounded-full", pos.days_held >= 12 ? "bg-red-500" : "bg-blue-500")} style={{ width: `${pct}%` }}></div>
          </div>
        </div>
      );
    }
    return <span className="text-sm text-gray-600">{pos.days_held}</span>;
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Symbol</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Entry</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Stop Loss</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">State</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Days Held</th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Action</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {positions.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-sm text-gray-500">
                  No open positions found.
                </td>
              </tr>
            ) : (
              positions.map((pos) => (
                <tr key={pos.id} className={clsx("hover:bg-gray-50", pos.position_state === "PENDING_MANUAL_EXIT" && "bg-red-50/30")}>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="font-bold text-gray-900">{pos.symbol}</div>
                    <div className="text-xs text-gray-500">{pos.sector}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-gray-900">₹{pos.entry_price.toLocaleString("en-IN")}</div>
                    <div className="text-xs text-gray-500">{new Date(pos.entry_date).toLocaleDateString("en-IN", {day:'2-digit', month:'short'})}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm font-medium text-red-600 flex flex-col">
                      <span>₹{pos.live_stop_loss.toLocaleString("en-IN")}</span>
                      {pos.live_stop_loss > pos.initial_stop_loss && (
                        <span className="text-[10px] text-green-600 bg-green-50 rounded px-1 w-fit mt-0.5 border border-green-100">Trailed Up</span>
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span 
                      className={clsx("px-2.5 py-1 inline-flex text-xs leading-5 font-semibold rounded-full border", getStateColor(pos.position_state))}
                      title={pos.position_state === "PARABOLIC_TRAILING" ? "Stock is accelerating vertically. Stop-loss has been tightened to 1x ATR." : ""}
                    >
                      {pos.position_state.replace(/_/g, " ")}
                      {pos.position_state === "PARABOLIC_TRAILING" && " 🚀"}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {getDaysHeldDisplay(pos)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium flex justify-end space-x-2 items-center">
                    {pos.partial_profit_triggered && (
                      <span className="animate-pulse bg-amber-100 text-amber-800 text-xs px-2 py-1 rounded-md border border-amber-300 flex items-center" title="Target reached! Execute in Kite. Engine will auto-record tonight.">
                        ⚡ Target Hit
                      </span>
                    )}
                    <button 
                      onClick={() => setClosingPos(pos)}
                      className="text-blue-600 hover:text-blue-900 bg-blue-50 px-3 py-1.5 rounded-md transition-colors"
                    >
                      Close
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {closingPos && <ClosePositionModal position={closingPos} onClose={() => setClosingPos(null)} />}
    </div>
  );
}
