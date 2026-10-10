import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRegime } from "../../api";
import clsx from "clsx";

export default function KillSwitchGauge() {
  const { data: regime } = useQuery({ queryKey: ["regime"], queryFn: fetchRegime });
  
  if (!regime) return null;

  const isActive = regime.kill_switch_active;

  // Gauge for when Kill Switch is OFF (Safe)
  if (!isActive) {
    // 0 is trigger point, higher is safer
    // Nifty dist > 0 means above 200 SMA
    const niftyDist = regime.nifty_distance_to_sma200_pct;
    // VIX dist < 0 means below trigger (e.g. 22)
    const vixDist = regime.vix_distance_to_trigger_pct;

    const niftyPct = Math.max(0, Math.min(100, 50 + (niftyDist * 5))); // Scale roughly: 10% above = 100% full
    const vixPct = Math.max(0, Math.min(100, 50 - (vixDist * 2))); // Scale roughly: 25% below = 100% full

    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 flex flex-col md:flex-row space-y-6 md:space-y-0 md:space-x-8">
        <div className="flex-1">
          <div className="flex justify-between text-sm font-medium mb-2">
            <span className="text-gray-700">Nifty 50 Health</span>
            <span className={clsx(niftyDist >= 0 ? "text-green-600" : "text-red-600")}>
              {niftyDist >= 0 ? `Safe +${niftyDist}%` : `Warning ${niftyDist}%`}
            </span>
          </div>
          <div className="w-full bg-red-100 rounded-full h-3">
            <div className="bg-gradient-to-r from-red-500 to-green-500 h-3 rounded-full" style={{ width: `${niftyPct}%` }}></div>
          </div>
          <p className="text-xs text-gray-500 mt-1">Distance above 200-SMA</p>
        </div>
        
        <div className="flex-1">
          <div className="flex justify-between text-sm font-medium mb-2">
            <span className="text-gray-700">VIX Danger Level</span>
            <span className={clsx(vixDist <= 0 ? "text-green-600" : "text-red-600")}>
              {vixDist <= 0 ? `${Math.abs(vixDist)}% below trigger` : `${vixDist}% above trigger`}
            </span>
          </div>
          <div className="w-full bg-red-100 rounded-full h-3">
            <div className="bg-gradient-to-r from-red-500 to-green-500 h-3 rounded-full" style={{ width: `${vixPct}%` }}></div>
          </div>
          <p className="text-xs text-gray-500 mt-1">Distance below trigger threshold</p>
        </div>
      </div>
    );
  }

  // Recovery Tracker for when Kill Switch is ON
  const niftyRecDist = regime.nifty_distance_to_sma50_pct;
  const vixRecDist = regime.vix_distance_to_reentry_pct;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-red-200 p-6 flex flex-col space-y-6">
      <h3 className="text-lg font-bold text-red-800 border-b border-red-100 pb-2">Recovery Tracker</h3>
      
      <div className="flex flex-col md:flex-row md:space-x-8 space-y-6 md:space-y-0">
        <div className="flex-1">
          <div className="flex justify-between text-sm font-medium mb-2">
            <span className="text-gray-700">Nifty Recovery (50-SMA)</span>
            <span className={clsx(niftyRecDist >= 0 ? "text-green-600" : "text-red-600")}>
              {niftyRecDist >= 0 ? `Target Hit (+${niftyRecDist}%)` : `${Math.abs(niftyRecDist)}% to re-entry`}
            </span>
          </div>
        </div>
        
        <div className="flex-1">
          <div className="flex justify-between text-sm font-medium mb-2">
            <span className="text-gray-700">VIX Cooldown</span>
            <span className={clsx(vixRecDist <= 0 ? "text-green-600" : "text-red-600")}>
              {vixRecDist <= 0 ? `Target Hit (${Math.abs(vixRecDist)}% below)` : `${vixRecDist}% above re-entry`}
            </span>
          </div>
        </div>
      </div>
      
      <div>
        <div className="flex justify-between text-sm font-medium mb-2">
          <span className="text-gray-700">Hysteresis Progress</span>
          <span className={regime.reentry_consecutive_count >= regime.reentry_sessions_required ? "text-green-600" : "text-amber-600"}>
            {regime.reentry_consecutive_count} / {regime.reentry_sessions_required} consecutive sessions
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-3">
          <div 
            className="bg-green-500 h-3 rounded-full transition-all" 
            style={{ width: `${regime.reentry_progress_pct || 0}%` }}
          ></div>
        </div>
      </div>
    </div>
  );
}
