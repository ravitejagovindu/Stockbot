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
  const isPositive = pnl_pct >= 0;
  return (
    <g>
      <text x={x + width + 10} y={y + height / 2 + 4} fill="#6b7280" fontSize={12} textAnchor="start">
        {value.toFixed(1)}%
      </text>
      <text x={x + width + 55} y={y + height / 2 + 4} fill={isPositive ? "#10b981" : "#ef4444"} fontSize={12} textAnchor="start" fontWeight="bold">
        {isPositive ? "+" : ""}{pnl_pct.toFixed(2)}%
      </text>
    </g>
  );
};

export default function SectorExposureBar({ data, maxPct }: SectorExposureProps) {
  const chartData = [...data].sort((a, b) => b.pct_of_equity - a.pct_of_equity);

  if (chartData.length === 0) {
    return (
      <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200 flex items-center justify-center h-48">
        <span className="text-gray-400">No sector exposure</span>
      </div>
    );
  }

  return (
    <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200 h-64">
      <h4 className="text-gray-500 font-medium mb-4 flex justify-between">
        <span>Sector Exposure (% of Equity)</span>
        <span className="text-xs text-gray-400">Est. P&L</span>
      </h4>
      <ResponsiveContainer width="100%" height="80%">
        <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 100, left: 0, bottom: 0 }}>
          <XAxis type="number" domain={[0, maxPct + 5]} hide />
          <YAxis dataKey="sector" type="category" width={120} tick={{ fontSize: 12 }} />
          <Tooltip cursor={{ fill: "#f3f4f6" }} formatter={(val: any, name: any, props: any) => [`${Number(val).toFixed(1)}% (P&L: ${props.payload.pnl_pct.toFixed(1)}%)`, "Exposure"]} />
          <ReferenceLine x={maxPct} stroke="red" strokeDasharray="3 3" label={{ position: "top", value: `Max ${maxPct}%`, fill: "red", fontSize: 12 }} />
          <Bar dataKey="pct_of_equity" fill="#3b82f6" radius={[0, 4, 4, 0]} label={<CustomLabel />} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
