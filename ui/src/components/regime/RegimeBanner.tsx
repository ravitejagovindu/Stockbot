import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRegime } from "../../api";
import { AlertTriangle, CheckCircle } from "lucide-react";
import clsx from "clsx";

export default function RegimeBanner() {
  const { data, isLoading, isError } = useQuery({ queryKey: ["regime"], queryFn: fetchRegime });

  if (isLoading) return <div className="h-16 bg-gray-200 animate-pulse rounded-lg mb-6" />;
  if (isError || !data) return null;

  const active = data.kill_switch_active;

  return (
    <div
      className={clsx(
        "flex items-center justify-between p-4 rounded-lg mb-6 shadow-sm",
        active ? "bg-red-50 border border-red-200" : "bg-green-50 border border-green-200"
      )}
    >
      <div className="flex items-center space-x-3">
        {active ? (
          <AlertTriangle className="w-6 h-6 text-red-600" />
        ) : (
          <CheckCircle className="w-6 h-6 text-green-600" />
        )}
        <div>
          <h3 className={clsx("font-semibold text-lg", active ? "text-red-800" : "text-green-800")}>
            {active ? "⚠️ KILL SWITCH ACTIVE — No New Entries" : "✓ Market Regime: ACTIVE"}
          </h3>
          <p className={clsx("text-sm", active ? "text-red-600" : "text-green-600")}>
            Nifty: {data.nifty_close.toLocaleString("en-IN")} | VIX: {data.vix_close.toFixed(2)}
          </p>
        </div>
      </div>

      {active && (
        <div className="text-right">
          <span className="text-sm font-medium text-red-800 block">Re-entry Progress</span>
          <span className="text-2xl font-bold text-red-600">
            {data.reentry_consecutive_count} / {data.reentry_sessions_required}
          </span>
          <span className="text-xs text-red-500 block">sessions qualifying</span>
        </div>
      )}
    </div>
  );
}
