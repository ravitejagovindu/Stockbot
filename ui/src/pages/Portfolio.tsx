import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchPortfolio } from "../api";
import HeatGauge from "../components/portfolio/HeatGauge";
import PositionTable from "../components/portfolio/PositionTable";
import { AlertTriangle } from "lucide-react";

export default function Portfolio() {
  const { data: portfolio, isLoading } = useQuery({ queryKey: ["portfolio"], queryFn: fetchPortfolio });

  if (isLoading) return <div className="p-8 text-center text-gray-500">Loading portfolio...</div>;

  const { positions = [], summary = {} } = portfolio || {};
  
  const alerts = positions.filter((p: any) => p.earnings_alert);

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-800">Portfolio Manager</h2>
      </div>

      {alerts.length > 0 && (
        <div className="space-y-3 mb-6">
          {alerts.map((pos: any) => (
            <div key={pos.id} className="bg-orange-50 border border-orange-200 p-4 rounded-lg flex items-center space-x-3 shadow-sm">
              <AlertTriangle className="w-6 h-6 text-orange-500" />
              <div>
                <h4 className="font-bold text-orange-800">⚠️ Earnings Alert: {pos.symbol}</h4>
                <p className="text-orange-700 text-sm">
                  Earnings or corporate action scheduled for {new Date(pos.next_earnings_date).toLocaleDateString("en-IN", {day:'2-digit', month:'short'})}. Review position.
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <HeatGauge 
          label="Open Positions" 
          value={summary.open_positions || 0} 
          max={summary.max_positions || 10} 
        />
        <HeatGauge 
          label="Portfolio Risk" 
          value={summary.total_risk_pct || 0} 
          max={summary.max_risk_pct || 10} 
          formatAsPct 
        />
      </div>

      <div className="pt-4">
        <PositionTable positions={positions} />
      </div>
    </div>
  );
}
