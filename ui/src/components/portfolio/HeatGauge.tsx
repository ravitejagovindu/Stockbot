import React from "react";
import clsx from "clsx";

interface HeatGaugeProps {
  label: string;
  value: number;
  max: number;
  formatAsPct?: boolean;
}

export default function HeatGauge({ label, value, max, formatAsPct = false }: HeatGaugeProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  
  let color = "bg-green-500";
  if (pct >= 80) color = "bg-orange-500";
  if (pct >= 95) color = "bg-red-500";

  const displayValue = formatAsPct ? `${value.toFixed(1)}%` : value.toString();
  const displayMax = formatAsPct ? `${max.toFixed(1)}%` : max.toString();

  return (
    <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
      <div className="flex justify-between items-end mb-4">
        <h4 className="text-gray-500 font-medium">{label}</h4>
        <div className="text-2xl font-bold text-gray-800">
          {displayValue} <span className="text-sm font-normal text-gray-400">/ {displayMax}</span>
        </div>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-3">
        <div className={clsx("h-3 rounded-full transition-all duration-500", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
