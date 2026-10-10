import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchPortfolio } from "../api";
import RegimeBanner from "../components/regime/RegimeBanner";
import KillSwitchGauge from "../components/regime/KillSwitchGauge";
import HeatGauge from "../components/portfolio/HeatGauge";
import SectorExposureBar from "../components/portfolio/SectorExposureBar";

export default function Dashboard() {
  const { data: portfolio, isLoading } = useQuery({ queryKey: ["portfolio"], queryFn: fetchPortfolio });

  if (isLoading) {
    return <div className="p-8 text-center text-gray-500">Loading dashboard...</div>;
  }

  const { summary, sector_performance } = portfolio || {};

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <RegimeBanner />
      <KillSwitchGauge />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <HeatGauge 
          label="Open Positions" 
          value={summary?.open_positions || 0} 
          max={summary?.max_positions || 10} 
        />
        <HeatGauge 
          label="Portfolio Risk" 
          value={summary?.total_risk_pct || 0} 
          max={summary?.max_risk_pct || 10} 
          formatAsPct 
        />
        <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
           <h4 className="text-gray-500 font-medium mb-2">Needs Attention</h4>
           {summary?.pending_manual_exits?.length > 0 || summary?.earnings_alerts?.length > 0 ? (
             <ul className="space-y-2 text-sm">
                {summary.earnings_alerts.map((sym: string) => (
                  <li key={`ea-${sym}`} className="text-orange-600 font-medium">⚠️ {sym}: Earnings Alert</li>
                ))}
                {summary.pending_manual_exits.map((sym: string) => (
                  <li key={`me-${sym}`} className="text-red-600 font-medium">⏱️ {sym}: Pending Exit (Time Decay)</li>
                ))}
             </ul>
           ) : (
             <p className="text-green-600 font-medium mt-4">✓ All positions healthy</p>
           )}
        </div>
      </div>

      <SectorExposureBar data={sector_performance || []} maxPct={summary?.max_sector_pct || 15} />
    </div>
  );
}
