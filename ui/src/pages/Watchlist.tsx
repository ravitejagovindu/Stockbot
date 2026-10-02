import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchWatchlist, fetchRegime } from "../api";
import RegimeBanner from "../components/regime/RegimeBanner";
import TradeTicketCard from "../components/watchlist/TradeTicketCard";
import { AlertCircle } from "lucide-react";

export default function Watchlist() {
  const { data: watchlist, isLoading: wlLoading } = useQuery({ queryKey: ["watchlist"], queryFn: () => fetchWatchlist() });
  const { data: regime } = useQuery({ queryKey: ["regime"], queryFn: fetchRegime });

  if (wlLoading) return <div className="p-8 text-center text-gray-500">Loading today's setups...</div>;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <RegimeBanner />

      {regime?.kill_switch_active ? (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-12 text-center">
          <AlertCircle className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h2 className="text-xl font-bold text-gray-700">No Setups Generated</h2>
          <p className="text-gray-500 mt-2">The macro kill switch is active. Capital preservation is prioritized.</p>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <h2 className="text-2xl font-bold text-gray-800">Approved Setups ({watchlist?.approved_count || 0})</h2>
            <span className="text-sm text-gray-500">Run Date: {watchlist?.run_date}</span>
          </div>

          {watchlist?.approved_count === 0 ? (
            <div className="bg-white border border-gray-200 rounded-xl p-12 text-center text-gray-500 shadow-sm">
              No candidates passed all screening and risk gates today.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {watchlist?.approved.map((setup) => (
                <TradeTicketCard key={setup.symbol} setup={setup} />
              ))}
            </div>
          )}

          {watchlist?.blocked_count ? (
            <div className="mt-12 pt-8 border-t border-gray-200">
              <h3 className="text-lg font-semibold text-gray-700 mb-4">Blocked Candidates ({watchlist.blocked_count})</h3>
              <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-600 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
                {watchlist.blocked.map((setup: any) => (
                  <div key={setup.symbol} className="flex justify-between border-b border-gray-200 pb-2">
                    <span className="font-medium">{setup.symbol}</span>
                    <span className="text-red-500 text-xs mt-0.5">{setup.block_reason}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
