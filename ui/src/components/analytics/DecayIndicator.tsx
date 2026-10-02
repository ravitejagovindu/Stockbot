import React from "react";
import clsx from "clsx";

interface DecayIndicatorProps {
  summary: any;
}

export default function DecayIndicator({ summary }: DecayIndicatorProps) {
  const { decay_ratio, decay_signal, decay_signal_description, rolling_3m, rolling_6m } = summary;

  const getColor = (signal: string) => {
    switch (signal) {
      case "HEALTHY": return "bg-green-100 text-green-800 border-green-200";
      case "MONITOR": return "bg-amber-100 text-amber-800 border-amber-200";
      case "WARNING": return "bg-orange-100 text-orange-800 border-orange-200";
      case "CRITICAL": return "bg-red-100 text-red-800 border-red-300 animate-pulse";
      default: return "bg-gray-100 text-gray-800";
    }
  };

  const getTextColor = (signal: string) => {
    switch (signal) {
      case "HEALTHY": return "text-green-600";
      case "MONITOR": return "text-amber-600";
      case "WARNING": return "text-orange-600";
      case "CRITICAL": return "text-red-600";
      default: return "text-gray-500";
    }
  };

  if (!decay_ratio && decay_signal === "INSUFFICIENT_DATA") {
    return (
      <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 text-center">
        <h3 className="text-gray-500 font-medium">Strategy Decay Signal</h3>
        <p className="text-xl font-bold mt-2 text-gray-800">Insufficient Data</p>
      </div>
    );
  }

  return (
    <div className={clsx("p-6 rounded-xl shadow-sm border", getColor(decay_signal))}>
      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="font-bold text-lg">Strategy Decay Signal: {decay_signal}</h3>
          <p className="text-sm opacity-80">{decay_signal_description}</p>
        </div>
        <div className={clsx("text-4xl font-black", getTextColor(decay_signal))}>
          {(decay_ratio * 100).toFixed(1)}%
        </div>
      </div>
      
      <div className="grid grid-cols-3 gap-4 pt-4 border-t border-black/10 text-sm font-medium">
        <div>
          <span className="block opacity-70 text-xs uppercase tracking-wider mb-1">All-Time</span>
          {(decay_ratio * 100).toFixed(1)}% realization
        </div>
        <div>
          <span className="block opacity-70 text-xs uppercase tracking-wider mb-1">Rolling 6M</span>
          {rolling_6m ? `${(rolling_6m * 100).toFixed(1)}%` : "N/A"}
        </div>
        <div>
          <span className="block opacity-70 text-xs uppercase tracking-wider mb-1">Rolling 3M</span>
          {rolling_3m ? `${(rolling_3m * 100).toFixed(1)}%` : "N/A"}
        </div>
      </div>
    </div>
  );
}
