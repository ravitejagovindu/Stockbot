import React from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

interface SectorExposureProps {
  data: Array<{
    sector: string;
    total_capital_deployed: number;
    pct_of_equity: number;
    estimated_pnl: number;
    pnl_pct: number;
  }>;
  maxPct: number;
}

const CustomLabel = (props: any) => {
  const { x, y, width, height, value, pnl_pct } = props;
  const isPositive = (pnl_pct || 0) >= 0;
  return (
    <g>
      <text x={x + width + 10} y={y + height / 2 + 4} fill="#94a3b8" fontSize={11} fontFamily="JetBrains Mono" textAnchor="start">
        {value.toFixed(1)}%
      </text>
      <text x={x + width + 60} y={y + height / 2 + 4} fill={isPositive ? "#34d399" : "#f43f5e"} fontSize={11} fontFamily="JetBrains Mono" textAnchor="start" fontWeight="600">
        {isPositive ? "+" : ""}{pnl_pct ? pnl_pct.toFixed(2) : "0.00"}%
      </text>
    </g>
  );
};

export default function SectorExposureBar({ data = [], maxPct = 15 }: SectorExposureProps) {
  const chartData = [...(data || [])].sort((a, b) => b.pct_of_equity - a.pct_of_equity);

  if (chartData.length === 0) {
    // Elegant zero-position cash defense state
    const defaultSectors = [
      { name: "Financial Services / Banking", color: "bg-indigo-500" },
      { name: "Information Technology", color: "bg-cyan-500" },
      { name: "Automotive & Components", color: "bg-amber-500" },
      { name: "Pharmaceuticals & Healthcare", color: "bg-emerald-500" },
    ];

    return (
      <div className="glass-card border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-white">Sector Concentration & Risk Guard</h3>
            <p className="text-xs text-slate-400">Enforces hard ceiling: max {maxPct}% total capital per sector.</p>
          </div>
          <span className="text-xs font-mono text-slate-400">Threshold: {maxPct}.0% Max</span>
        </div>

        <div className="space-y-3 pt-2">
          {defaultSectors.map((s) => (
            <div key={s.name}>
              <div className="flex justify-between text-xs font-mono mb-1">
                <span className="text-slate-300">{s.name}</span>
                <span className="text-slate-400">0.0% / {maxPct}.0% Limit</span>
              </div>
              <div className="w-full h-2 rounded-full bg-slate-800 relative">
                <div className={`h-full ${s.color} rounded-full`} style={{ width: "0%" }} />
              </div>
            </div>
          ))}
        </div>

        <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800 flex items-center justify-between text-xs">
          <span className="text-slate-400">Currently in 100% Cash Defense. No active sector concentrations.</span>
          <span className="text-emerald-400 font-mono font-medium">✓ Safe Margin</span>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-card border border-slate-800 rounded-2xl p-6 space-y-4 h-80 flex flex-col justify-between">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Sector Concentration & Risk Guard</h3>
          <p className="text-xs text-slate-400">Max {maxPct}% total capital per sector limit.</p>
        </div>
        <span className="text-xs font-mono text-slate-400">Hard Cap: {maxPct}%</span>
      </div>

      <div className="flex-1 w-full pt-2">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 110, left: 10, bottom: 0 }}>
            <XAxis type="number" domain={[0, maxPct + 5]} hide />
            <YAxis 
              dataKey="sector" 
              type="category" 
              width={140} 
              tick={{ fontSize: 11, fill: "#cbd5e1", fontFamily: "Plus Jakarta Sans" }} 
            />
            <Tooltip 
              contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155", borderRadius: "0.75rem", fontSize: "12px", color: "#f8fafc" }}
              formatter={(val: any, name: any, props: any) => [
                `${Number(val).toFixed(1)}% (P&L: ${props.payload.pnl_pct ? props.payload.pnl_pct.toFixed(1) : 0}%)`, 
                "Exposure"
              ]} 
            />
            <ReferenceLine 
              x={maxPct} 
              stroke="#f43f5e" 
              strokeDasharray="3 3" 
              label={{ position: "top", value: `Cap ${maxPct}%`, fill: "#f43f5e", fontSize: 11, fontFamily: "JetBrains Mono" }} 
            />
            <Bar dataKey="pct_of_equity" fill="#3b82f6" radius={[0, 4, 4, 0]} label={<CustomLabel />} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
