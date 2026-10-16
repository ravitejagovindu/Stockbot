import React from "react";
import clsx from "clsx";

interface HeatGaugeProps {
  label: string;
  value: number;
  max: number;
  formatAsPct?: boolean;
}

export default function HeatGauge({ label, value, max, formatAsPct = false }: HeatGaugeProps) {
  const pct = Math.min(100, Math.max(0, (value / (max || 1)) * 100));
  const isPositions = label.toLowerCase().includes("position");

  const displayValue = formatAsPct ? `${value.toFixed(1)}%` : value.toString();
  const displayMax = formatAsPct ? `${max.toFixed(1)}%` : max.toString();

  // If it's the positions gauge:
  if (isPositions) {
    const totalSlots = max || 12;
    const slots = Array.from({ length: totalSlots }, (_, i) => i + 1);
    return (
      <div className="glass-card border border-slate-800 rounded-2xl p-5 space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 font-mono">
            {label}
          </span>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            {value} / {totalSlots} USED
          </span>
        </div>
        <div>
          <div className="flex items-baseline space-x-2">
            <span className="text-3xl font-extrabold text-white font-mono tabular-nums tracking-tight">
              {displayValue}
            </span>
            <span className="text-xs text-slate-400 font-mono">/ {displayMax} Active Positions</span>
          </div>
          <p className="text-xs text-slate-400 mt-1">1% Max Risk per position allocation</p>
        </div>
        {/* Discrete Slot Blocks */}
        <div 
          className="grid gap-1.5 pt-2" 
          style={{ gridTemplateColumns: `repeat(${totalSlots}, minmax(0, 1fr))` }}
        >
          {slots.map((slotNum) => {
            const isFilled = slotNum <= value;
            return (
              <div
                key={slotNum}
                className={clsx(
                  "h-5 rounded border flex items-center justify-center text-[10px] font-mono transition-all",
                  isFilled
                    ? "bg-blue-600 border-blue-400 text-white shadow-sm shadow-blue-500/50"
                    : "bg-slate-800/80 border-slate-700/50 text-slate-400"
                )}
              >
                {slotNum}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Risk Heat Gauge:
  return (
    <div className="glass-card border border-slate-800 rounded-2xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 font-mono">
          {label}
        </span>
        <span
          className={clsx(
            "text-[10px] font-mono px-2 py-0.5 rounded border",
            pct >= 80
              ? "bg-rose-500/10 text-rose-400 border-rose-500/20"
              : pct >= 50
              ? "bg-amber-500/10 text-amber-300 border-amber-500/20"
              : "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
          )}
        >
          {pct >= 80 ? "HIGH RISK" : pct >= 50 ? "CAUTION" : "SAFE"}
        </span>
      </div>
      <div>
        <div className="flex items-baseline space-x-2">
          <span className="text-3xl font-extrabold text-white font-mono tabular-nums tracking-tight">
            {displayValue}
          </span>
          <span className="text-xs text-slate-400 font-mono">/ {displayMax} Max Cap</span>
        </div>
        <p className="text-xs text-slate-400 mt-1">1% Max Risk per position allocation</p>
      </div>
      {/* Risk Progress Bar with 10% Caution Notch */}
      <div className="space-y-1.5 pt-2">
        <div className="flex justify-between text-xs font-mono">
          <span className="text-slate-400">Risk Budget</span>
          <span className={clsx(pct >= 80 ? "text-rose-400" : "text-emerald-400")}>
            {Math.max(0, max - value).toFixed(1)}% Available
          </span>
        </div>
        <div className="w-full h-2 rounded-full bg-slate-800 relative">
          <div
            className={clsx(
              "h-full rounded-full transition-all duration-500",
              pct >= 80 ? "bg-rose-500" : pct >= 50 ? "bg-amber-500" : "bg-emerald-500"
            )}
            style={{ width: `${pct}%` }}
          />
          <div 
            className="absolute top-0 bottom-0 w-0.5 bg-amber-500 z-10" 
            style={{ left: `${Math.min(95, Math.round((10 / (max || 15)) * 100))}%` }} 
            title="10.0% Risk Warning Threshold" 
          />
        </div>
      </div>
    </div>
  );
}
