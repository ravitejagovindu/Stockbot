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

  const isInsufficient = decay_ratio === undefined || decay_ratio === null || decay_signal === "INSUFFICIENT_DATA";

  if (isInsufficient) {
    return (
      <div className="glass-card border border-blue-500/20 rounded-2xl p-6 relative overflow-hidden">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 relative z-10">
          <div className="space-y-1">
            <div className="flex items-center space-x-2">
              <span className="w-2.5 h-2.5 rounded-full bg-blue-400 animate-pulse" />
              <span className="text-xs font-mono uppercase tracking-wider text-slate-400">
                Model Robustness Signal: CALIBRATING
              </span>
            </div>
            <h3 className="text-lg font-bold text-white tracking-tight">
              Alpha Engine Calibrated — R:R Realization Model
            </h3>
            <p className="text-xs text-slate-400">
              Measures trade execution efficiency (Realized R:R vs Projected R:R). Minimum 10 closed trades required for statistical significance.
            </p>
          </div>
          
          <div className="text-left md:text-right font-mono bg-slate-900/60 border border-slate-800 p-3 rounded-xl">
            <p className="text-[11px] text-slate-400 uppercase tracking-wider">R:R Realization Ratio</p>
            <p className="text-2xl font-extrabold text-blue-400 mt-0.5">1.00 <span className="text-xs text-slate-400 font-normal">Base</span></p>
            <p className="text-[10px] text-slate-400">Healthy &ge; 0.80 • Critical &lt; 0.50</p>
          </div>
        </div>
      </div>
    );
  }

  const ratio = Number(decay_ratio);
  const isHealthy = decay_signal === "HEALTHY" || ratio >= 0.80;
  const isMonitor = decay_signal === "MONITOR" || (ratio >= 0.60 && ratio < 0.80);
  const isWarning = decay_signal === "WARNING" || (ratio >= 0.50 && ratio < 0.60);

  // Percentage for the gauge indicator (0.0 to 1.2 scale clamped between 0 and 100%)
  const gaugePercent = Math.min(100, Math.max(0, (ratio / 1.2) * 100));

  return (
    <div
      className={clsx(
        "rounded-2xl p-6 relative overflow-hidden transition-all duration-300 border",
        isHealthy 
          ? "glass-success border-emerald-500/30" 
          : isMonitor 
          ? "glass-card border-cyan-500/30"
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
                isHealthy ? "bg-emerald-400" : isMonitor ? "bg-cyan-400" : isWarning ? "bg-amber-400" : "bg-rose-500"
              )}
            />
            <span className="text-xs font-mono uppercase tracking-wider text-slate-400">
              Model Robustness: {decay_signal || (isHealthy ? "HEALTHY" : isMonitor ? "MONITOR" : isWarning ? "WARNING" : "CRITICAL")}
            </span>
          </div>
          <h3 className="text-lg font-bold text-white tracking-tight">
            {isHealthy 
              ? "Alpha Engine Robust — High Realization Ratio" 
              : isMonitor
              ? "Alpha Monitor — Moderate Execution Drag"
              : isWarning
              ? "Alpha Warning — Elevated Slippage / Premature Exits"
              : "Critical Degradation — Strategy Alpha Decayed"}
          </h3>
          <p className="text-xs text-slate-300/80">
            {decay_signal_description || "Realized R:R matches projected entry distribution within expected statistical tolerance."}
          </p>
        </div>
        
        <div className="text-left md:text-right font-mono bg-slate-900/80 border border-slate-800 p-3 rounded-xl shrink-0">
          <p className="text-[11px] text-slate-400 uppercase tracking-wider">R:R Realization Ratio</p>
          <p
            className={clsx(
              "text-2xl font-extrabold mt-0.5",
              isHealthy ? "text-emerald-400" : isMonitor ? "text-cyan-400" : isWarning ? "text-amber-400" : "text-rose-400"
            )}
          >
            {ratio.toFixed(2)}
          </p>
          <p className="text-[10px] text-slate-400">Healthy &ge; 0.80 • Critical &lt; 0.50</p>
        </div>
      </div>

      {/* 4-Zone Benchmark Visual Strip */}
      <div className="mt-4 pt-3 border-t border-slate-800/80 space-y-1.5">
        <div className="flex justify-between text-[10px] font-mono text-slate-400">
          <span className="text-rose-400">&lt; 0.50 Critical</span>
          <span className="text-amber-400">0.50 - 0.60 Warning</span>
          <span className="text-cyan-400">0.60 - 0.80 Monitor</span>
          <span className="text-emerald-400">&ge; 0.80 Optimal Alpha</span>
        </div>
        <div className="w-full h-2 rounded-full bg-slate-950 flex overflow-hidden relative border border-slate-800">
          <div className="w-[41.6%] bg-rose-500/40" title="Critical Zone (< 0.50)" />
          <div className="w-[8.4%] bg-amber-500/40" title="Warning Zone (0.50 - 0.60)" />
          <div className="w-[16.6%] bg-cyan-500/40" title="Monitor Zone (0.60 - 0.80)" />
          <div className="w-[33.4%] bg-emerald-500/40" title="Healthy Zone (>= 0.80)" />
          
          {/* Active Value Indicator Needle */}
          <div 
            className="absolute top-0 bottom-0 w-1 bg-white shadow-md shadow-white transition-all duration-500"
            style={{ left: `calc(${gaugePercent}% - 2px)` }}
            title={`Current Realization Ratio: ${ratio.toFixed(2)}`}
          />
        </div>
      </div>

      {/* Rolling breakdown */}
      <div className="grid grid-cols-3 gap-4 pt-3 mt-3 border-t border-slate-800/60 text-xs font-mono">
        <div>
          <span className="block text-slate-400 text-[10px] uppercase tracking-wider mb-0.5">All-Time Realization</span>
          <span className="text-white font-bold text-sm">
            {(ratio * 100).toFixed(1)}%
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
