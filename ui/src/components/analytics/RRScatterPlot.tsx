import React from "react";
import { 
  ScatterChart, 
  Scatter, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer, 
  ReferenceLine 
} from "recharts";
import { Info } from "lucide-react";

interface RRScatterPlotProps {
  trades: any[];
}

const CustomTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    const d = payload[0].payload;
    return (
      <div className="bg-[#0f172a] p-3.5 border border-slate-700/80 shadow-2xl rounded-xl font-mono text-xs text-slate-100 space-y-1">
        <p className="font-bold text-white text-sm">{d.symbol}</p>
        <div className="flex justify-between gap-4 text-slate-300">
          <span>Projected:</span>
          <span className="text-white font-bold">{d.projected.toFixed(2)} R</span>
        </div>
        <div className="flex justify-between gap-4 text-slate-300">
          <span>Realized:</span>
          <span className={d.realized >= 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
            {d.realized.toFixed(2)} R
          </span>
        </div>
        <p className="text-[10px] text-slate-400 pt-1 border-t border-slate-800 uppercase tracking-wider">
          Exit: {d.reason.replace(/_/g, " ")}
        </p>
      </div>
    );
  }
  return null;
};

export default function RRScatterPlot({ trades = [] }: RRScatterPlotProps) {
  const data = trades.map((t) => ({
    symbol: t.symbol,
    projected: t.projected_rr || 1.5,
    realized: t.realized_rr || 0,
    reason: t.exit_reason || "MANUAL",
    fill: t.realized_rr >= (t.projected_rr || 1.5) 
      ? "#34d399" 
      : t.realized_rr > 0 
      ? "#fbbf24" 
      : "#f43f5e",
  }));

  const maxVal = Math.max(
    ...data.map((d) => d.projected), 
    ...data.map((d) => d.realized),
    4
  );

  return (
    <div className="glass-card border border-slate-800 rounded-2xl p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Realized vs. Projected R:R</h3>
          <p className="text-xs text-slate-400">
            Scatter plots actual trade payoffs against initial 1:1.5 parity line.
          </p>
        </div>
        <span className="text-xs font-mono px-2.5 py-1 rounded bg-slate-800 text-slate-400 border border-slate-700">
          Target Parity: 1.5 R
        </span>
      </div>

      <div className="relative h-80 w-full bg-slate-950/70 border border-slate-800 rounded-xl flex items-center justify-center p-2 overflow-hidden">
        {trades.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950/80 z-10 p-6 text-center space-y-2">
            <Info className="w-8 h-8 text-slate-500 mb-1" />
            <p className="font-semibold text-slate-200 text-sm">Awaiting Closed Trades</p>
            <p className="text-xs text-slate-400 max-w-md">
              Realized vs. Projected R:R will scatter-plot payoffs against the 1:1.5 parity line once live positions close.
            </p>
          </div>
        )}

        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 20, right: 30, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(51, 65, 85, 0.4)" vertical={false} />
            <XAxis 
              type="number" 
              dataKey="projected" 
              name="Projected R:R" 
              domain={[0, Math.ceil(maxVal)]} 
              tick={{ fontSize: 11, fill: "#94a3b8", fontFamily: "JetBrains Mono" }} 
              label={{ value: "Projected R:R (Target)", position: "insideBottom", offset: -10, fill: "#64748b", fontSize: 11 }}
            />
            <YAxis 
              type="number" 
              dataKey="realized" 
              name="Realized R:R" 
              domain={[Math.floor(Math.min(0, ...data.map((d) => d.realized))), Math.ceil(maxVal)]} 
              tick={{ fontSize: 11, fill: "#94a3b8", fontFamily: "JetBrains Mono" }} 
              label={{ value: "Realized Payoff", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ strokeDasharray: "3 3", stroke: "#475569" }} />
            <ReferenceLine y={0} stroke="#475569" />
            <ReferenceLine 
              segment={[{ x: 0, y: 0 }, { x: maxVal, y: maxVal }]} 
              stroke="#64748b" 
              strokeDasharray="4 4" 
              label={{ value: "Perfect Parity (y = x)", fill: "#94a3b8", fontSize: 11, fontFamily: "JetBrains Mono", position: "insideTopRight" }} 
            />
            <Scatter name="Trades" data={data} fill="#3b82f6" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center justify-between text-xs text-slate-400 font-mono pt-1">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-400" /> Profitable Exit (&ge; 1.5R)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-amber-400" /> Time Decay Exit (0 to 1.5R)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-rose-400" /> Hit Hard Stop (-1.0R)
        </span>
      </div>
    </div>
  );
}
