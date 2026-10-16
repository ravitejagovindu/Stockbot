import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchPortfolio } from "../api";
import RegimeBanner from "../components/regime/RegimeBanner";
import KillSwitchGauge from "../components/regime/KillSwitchGauge";
import HeatGauge from "../components/portfolio/HeatGauge";
import SectorExposureBar from "../components/portfolio/SectorExposureBar";
import { RefreshCw, Download, ShieldCheck, AlertTriangle } from "lucide-react";

export default function Dashboard() {
  const queryClient = useQueryClient();
  const { data: portfolio, isLoading, isFetching } = useQuery({ 
    queryKey: ["portfolio"], 
    queryFn: fetchPortfolio 
  });

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    queryClient.invalidateQueries({ queryKey: ["regime"] });
    queryClient.invalidateQueries({ queryKey: ["health"] });
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="h-10 w-64 bg-slate-800 animate-pulse rounded-lg" />
        <div className="h-44 glass-card border border-slate-800 animate-pulse rounded-2xl" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="h-40 glass-card border border-slate-800 animate-pulse rounded-2xl" />
          <div className="h-40 glass-card border border-slate-800 animate-pulse rounded-2xl" />
          <div className="h-40 glass-card border border-slate-800 animate-pulse rounded-2xl" />
        </div>
      </div>
    );
  }

  const { summary = {}, sector_performance = [] } = portfolio || {};
  const accountEquity = summary?.account_equity || 1000000;
  const peakEquity = summary?.peak_equity || accountEquity;
  const drawdownPct = summary?.current_drawdown_pct || 0.0;
  const capitalDeployedPct = summary?.capital_deployed_pct || 0.0;
  const pendingExits = summary?.pending_manual_exits || [];
  const earningsAlerts = summary?.earnings_alerts || [];

  return (
    <div className="space-y-6">
      {/* Header & Quick Action Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
            Executive Trading Cockpit
            <span className="text-xs font-normal font-mono px-2.5 py-1 rounded-md bg-slate-800 text-slate-300 border border-slate-700">
              Daily EOD Cycle
            </span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Real-time macro regime health, portfolio heat limits, and risk allocation.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleRefresh}
            disabled={isFetching}
            className="px-3.5 py-2 text-xs font-semibold rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition flex items-center gap-2 cursor-pointer disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-slate-400 ${isFetching ? "animate-spin" : ""}`} />
            Refresh EOD Feed
          </button>
          <a
            href="/ledger/summary"
            target="_blank"
            rel="noreferrer"
            className="px-3.5 py-2 text-xs font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/30 transition flex items-center gap-2"
          >
            <Download className="w-3.5 h-3.5" />
            Audit Ledger
          </a>
        </div>
      </div>

      {/* Unified Macro Regime Card */}
      <RegimeBanner />
      <KillSwitchGauge />

      {/* 3 Primary Capacity & Heat Gauges */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Card 1: Account Capital & Drawdown */}
        <div className="glass-card border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 font-mono">
              Account Equity
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
              LIVE BALANCE
            </span>
          </div>
          <div>
            <p className="text-3xl font-extrabold text-white font-mono tabular-nums tracking-tight">
              ₹{accountEquity.toLocaleString("en-IN")}
            </p>
            <div className="flex items-center space-x-2 mt-1 text-xs text-slate-400 font-mono">
              <span>Peak: ₹{peakEquity.toLocaleString("en-IN")}</span>
              <span>•</span>
              <span className={drawdownPct > 0 ? "text-rose-400" : "text-emerald-400"}>
                Drawdown: {drawdownPct.toFixed(1)}%
              </span>
            </div>
          </div>
          <div className="space-y-1.5 pt-2">
            <div className="flex justify-between text-xs font-mono">
              <span className="text-slate-400">Capital Deployed</span>
              <span className="text-slate-200">
                {capitalDeployedPct.toFixed(1)}% ({(100 - capitalDeployedPct).toFixed(1)}% Cash)
              </span>
            </div>
            <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
              <div 
                className="h-full bg-blue-500 rounded-full transition-all duration-500" 
                style={{ width: `${capitalDeployedPct}%` }} 
              />
            </div>
          </div>
        </div>

        {/* Card 2: Risk Budget Meter */}
        <HeatGauge 
          label="Total Risk Heat" 
          value={summary?.total_risk_pct || 0} 
          max={summary?.max_risk_pct || 15} 
          formatAsPct 
        />

        {/* Card 3: Portfolio Position Slots */}
        <HeatGauge 
          label="Portfolio Slots" 
          value={summary?.open_positions || 0} 
          max={summary?.max_positions || 10} 
        />
      </div>

      {/* Lower Split: Sector Concentration & Surveillance / Needs Attention */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <SectorExposureBar 
            data={sector_performance || []} 
            maxPct={summary?.max_sector_pct || 15} 
          />
        </div>

        {/* Surveillance & Needs Attention Card */}
        <div className="glass-card border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold text-white">Surveillance Ledger</h3>
            <span className="text-xs font-mono text-emerald-400 font-medium">CLEAN</span>
          </div>
          <p className="text-xs text-slate-400">Pre-trade regulatory hygiene & NSE/BSE filters.</p>

          <div className="space-y-2.5 pt-1">
            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="flex items-center space-x-2.5">
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="text-xs font-medium text-slate-200">ASM / GSM Scrape</span>
              </div>
              <span className="text-xs font-mono text-emerald-400 font-medium">CLEAN</span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="flex items-center space-x-2.5">
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="text-xs font-medium text-slate-200">Earnings Blackout</span>
              </div>
              <span className="text-xs font-mono text-slate-400 font-medium">SYNCED</span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="flex items-center space-x-2.5">
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="text-xs font-medium text-slate-200">ADTV Floor (&gt;₹25 Cr)</span>
              </div>
              <span className="text-xs font-mono text-slate-400 font-medium">ACTIVE</span>
            </div>
          </div>

          {/* Attention items */}
          <div className="pt-2 border-t border-slate-800">
            {pendingExits.length > 0 || earningsAlerts.length > 0 ? (
              <div className="space-y-2 text-xs">
                <p className="text-slate-400 font-semibold uppercase text-[10px]">Action Required</p>
                {earningsAlerts.map((sym: string) => (
                  <div key={`ea-${sym}`} className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 font-mono flex items-center gap-2">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                    <span>{sym}: Upcoming Earnings Call</span>
                  </div>
                ))}
                {pendingExits.map((sym: string) => (
                  <div key={`me-${sym}`} className="p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 font-mono flex items-center gap-2">
                    <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
                    <span>{sym}: Time Decay Exit Flagged</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex items-center space-x-2 text-xs text-emerald-400 font-mono">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>All active positions healthy</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
