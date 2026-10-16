import React from "react";
import clsx from "clsx";

interface DecayIndicatorProps {
  summary: any;
}

export default function DecayIndicator({ summary = {} }: DecayIndicatorProps) {
  const { 
    decay_ratio, 
    decay_signal = "INSUFFICIENT_DATA", 
    decay_signal_description, 
    rolling_3m, 
    rolling_6m 
  } = summary;

  const isInsufficient = !decay_ratio && decay_signal === "INSUFFICIENT_DATA";

  if (isInsufficient) {
    return (
      <div className="glass-card border border-blue-500/20 rounded-2xl p-6 relative overflow-hidden">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 relative z-10">
          <div className="space-y-1">
            <div className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-blue-400 animate-pulse" />
              <span className="text-xs font-mono uppercase tracking-wider text-slate-400">
                Model Robustness Signal
              </span>
            </div>
            <h3 className="text-lg font-bold text-white tracking-tight">
              Alpha Engine Calibrated — Initial Production Mode
            </h3>
            <p className="text-xs text-slate-400">
              Strategy decay and edge drift calculations initiate automatically once closed live trades are logged.
            </p>
          </div>
          
          <div className="text-left md:text-right font-mono bg-slate-900/60 border border-slate-800 p-3 rounded-xl">
            <p className="text-[11px] text-slate-400 uppercase tracking-wider">Strategy Decay Index</p>
            <p className="text-2xl font-extrabold text-blue-400 mt-0.5">0.00</p>
            <p className="text-[10px] text-slate-400">Decay threshold &gt; 0.50</p>
          </div>
        </div>
      </div>
    );
  }

  const isHealthy = decay_signal === "HEALTHY";
  const isWarning = decay_signal === "WARNING" || decay_signal === "MONITOR";

  return (
    <div
      className={clsx(
        "rounded-2xl p-6 relative overflow-hidden transition-all duration-300 border",
        isHealthy 
          ? "glass-success border-emerald-500/30" 
          : isWarning 
          ? "glass-card border-amber-500/30" 
          : "glass-danger border-rose-500/30"
      )}
    >
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 relative z-10">
        <div className="space-y-1">
          <div className="flex items-center space-x-2">
            <span
              className={clsx(
                "w-2.5 h-2.5 rounded-full animate-pulse",
                isHealthy ? "bg-emerald-400" : isWarning ? "bg-amber-400" : "bg-rose-500"
              )}
            />
            <span className="text-xs font-mono uppercase tracking-wider text-slate-400">
              Model Robustness Signal: {decay_signal}
            </span>
          </div>
          <h3 className="text-lg font-bold text-white tracking-tight">
            {isHealthy 
              ? "Alpha Engine Healthy — Zero Drift Detected" 
              : `Alpha Edge Attention: ${decay_signal}`}
          </h3>
          <p className="text-xs text-slate-300/80">
            {decay_signal_description || "Execution metrics match backtest distributions within statistical tolerance."}
          </p>
        </div>
        
        <div className="text-left md:text-right font-mono bg-slate-900/80 border border-slate-800 p-3 rounded-xl">
          <p className="text-[11px] text-slate-400 uppercase tracking-wider">Strategy Decay Index</p>
          <p
            className={clsx(
              "text-2xl font-extrabold mt-0.5",
              isHealthy ? "text-emerald-400" : isWarning ? "text-amber-400" : "text-rose-400"
            )}
          >
            {(decay_ratio || 0).toFixed(2)}
          </p>
          <p className="text-[10px] text-slate-400">Decay threshold &gt; 0.50</p>
        </div>
      </div>

      {/* Rolling breakdown */}
      <div className="grid grid-cols-3 gap-4 pt-4 mt-4 border-t border-slate-800/80 text-xs font-mono">
        <div>
          <span className="block text-slate-400 text-[10px] uppercase tracking-wider mb-0.5">All-Time Realization</span>
          <span className="text-white font-bold text-sm">
            {(decay_ratio * 100).toFixed(1)}%
          </span>
        </div>
        <div>
          <span className="block text-slate-400 text-[10px] uppercase tracking-wider mb-0.5">Rolling 6-Month</span>
          <span className="text-slate-200 font-bold text-sm">
            {rolling_6m ? `${(rolling_6m * 100).toFixed(1)}%` : "Calibrating"}
          </span>
        </div>
        <div>
          <span className="block text-slate-400 text-[10px] uppercase tracking-wider mb-0.5">Rolling 3-Month</span>
          <span className="text-slate-200 font-bold text-sm">
            {rolling_3m ? `${(rolling_3m * 100).toFixed(1)}%` : "Calibrating"}
          </span>
        </div>
      </div>
    </div>
  );
}
