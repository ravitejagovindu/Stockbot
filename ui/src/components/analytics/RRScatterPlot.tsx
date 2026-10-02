import React from "react";
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

interface RRScatterPlotProps {
  trades: any[];
}

export default function RRScatterPlot({ trades }: RRScatterPlotProps) {
  const data = trades.map((t) => ({
    symbol: t.symbol,
    projected: t.projected_rr,
    realized: t.realized_rr,
    reason: t.exit_reason,
    fill: t.realized_rr >= t.projected_rr ? "#22c55e" : t.realized_rr > 0 ? "#eab308" : "#ef4444",
  }));

  const maxVal = Math.max(
    ...data.map(d => d.projected), 
    ...data.map(d => d.realized),
    4
  );

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const d = payload[0].payload;
      return (
        <div className="bg-white p-3 border border-gray-200 shadow-md rounded-md">
          <p className="font-bold text-gray-900">{d.symbol}</p>
          <p className="text-sm text-gray-600">Proj: {d.projected.toFixed(2)}R</p>
          <p className="text-sm text-gray-600">Real: {d.realized.toFixed(2)}R</p>
          <p className="text-xs text-gray-400 mt-1 uppercase">{d.reason}</p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 h-96">
      <h3 className="text-lg font-bold text-gray-800 mb-6">Realized vs Projected R:R</h3>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis type="number" dataKey="projected" name="Projected R:R" domain={[0, Math.ceil(maxVal)]} tick={{fontSize: 12}} />
          <YAxis type="number" dataKey="realized" name="Realized R:R" domain={[Math.floor(Math.min(0, ...data.map(d => d.realized))), Math.ceil(maxVal)]} tick={{fontSize: 12}} />
          <Tooltip content={<CustomTooltip />} cursor={{ strokeDasharray: '3 3' }} />
          <ReferenceLine y={0} stroke="#cbd5e1" />
          <ReferenceLine segment={[{ x: 0, y: 0 }, { x: maxVal, y: maxVal }]} stroke="#94a3b8" strokeDasharray="3 3" label={{ value: "Perfect Realization (y=x)", fill: "#94a3b8", fontSize: 12, position: "insideBottomRight" }} />
          <Scatter name="Trades" data={data} fill="#8884d8" />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
