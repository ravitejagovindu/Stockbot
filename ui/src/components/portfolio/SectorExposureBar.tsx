import React from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

interface SectorExposureProps {
  data: Record<string, number>;
  maxPct: number;
}

export default function SectorExposureBar({ data, maxPct }: SectorExposureProps) {
  const chartData = Object.entries(data)
    .map(([sector, pct]) => ({ sector, pct }))
    .sort((a, b) => b.pct - a.pct);

  if (chartData.length === 0) {
    return (
      <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200 flex items-center justify-center h-48">
        <span className="text-gray-400">No sector exposure</span>
      </div>
    );
  }

  return (
    <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200 h-64">
      <h4 className="text-gray-500 font-medium mb-4">Sector Exposure (% of Equity)</h4>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 20, left: 0, bottom: 0 }}>
          <XAxis type="number" domain={[0, maxPct + 5]} hide />
          <YAxis dataKey="sector" type="category" width={120} tick={{ fontSize: 12 }} />
          <Tooltip cursor={{ fill: "#f3f4f6" }} formatter={(val: any) => [`${Number(val).toFixed(1)}%`, "Exposure"]} />
          <ReferenceLine x={maxPct} stroke="red" strokeDasharray="3 3" label={{ position: "top", value: `Max ${maxPct}%`, fill: "red", fontSize: 12 }} />
          <Bar dataKey="pct" fill="#3b82f6" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
