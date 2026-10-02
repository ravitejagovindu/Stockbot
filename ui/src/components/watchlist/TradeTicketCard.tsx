import React from "react";
import clsx from "clsx";

export default function TradeTicketCard({ setup }: { setup: any }) {
  const isGreen = setup.projected_rr >= 1.5;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
      <div className="p-5 border-b border-gray-100 flex justify-between items-start">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">{setup.symbol}</h2>
          <span className="text-sm text-gray-500">{setup.sector || "Unknown Sector"}</span>
        </div>
        <div className={clsx("px-3 py-1 rounded-full text-sm font-bold", isGreen ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800")}>
          R:R {setup.projected_rr.toFixed(2)}
        </div>
      </div>
      
      <div className="p-5 space-y-4 flex-1">
        <div className="flex justify-between items-center">
          <span className="text-gray-500">Entry Price</span>
          <span className="font-medium text-lg">₹{setup.entry_price.toLocaleString("en-IN")}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-gray-500">Live Stop Loss</span>
          <span className="font-medium text-lg text-red-600 flex items-center">
            ₹{setup.live_stop_loss.toLocaleString("en-IN")}
            <span className="ml-2 text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded">
              {setup.active_stop}
            </span>
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-gray-500">Target (Resist.)</span>
          <span className="font-medium text-lg text-green-600">₹{setup.initial_resistance_target.toLocaleString("en-IN")}</span>
        </div>
        
        <div className="pt-4 border-t border-gray-100">
          <div className="bg-blue-50 rounded p-3 text-sm text-blue-900 space-y-1">
            <div className="flex justify-between font-bold">
              <span>Sizing: Buy {setup.shares} shares</span>
              <span>Total: ₹{setup.position_value.toLocaleString("en-IN")}</span>
            </div>
            <div className="text-blue-700 text-xs">
              Risking ₹{setup.risk_amount.toLocaleString("en-IN")} ({setup.risk_pct_of_equity.toFixed(2)}% of equity)
            </div>
          </div>
        </div>
      </div>
      
      <div className="bg-gray-50 p-3 text-center text-xs text-gray-500 border-t border-gray-200 uppercase tracking-wider">
        Execute manually in Kite terminal
      </div>
    </div>
  );
}
