import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAnalytics } from "../api";
import DecayIndicator from "../components/analytics/DecayIndicator";
import RRScatterPlot from "../components/analytics/RRScatterPlot";

export default function Analytics() {
  const { data: analytics, isLoading } = useQuery({ queryKey: ["analytics"], queryFn: () => fetchAnalytics(200) });

  if (isLoading) return <div className="p-8 text-center text-gray-500">Loading analytics...</div>;

  const { summary = {}, trades = [] } = analytics || {};

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-2xl font-bold text-gray-800">Trade Analytics</h2>
      </div>

      <DecayIndicator summary={summary} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-200 text-center">
          <div className="text-gray-500 text-sm font-medium mb-1">Total Trades</div>
          <div className="text-2xl font-bold text-gray-800">{summary.total_trades || 0}</div>
        </div>
        <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-200 text-center">
          <div className="text-gray-500 text-sm font-medium mb-1">Win Rate</div>
          <div className="text-2xl font-bold text-gray-800">
            {summary.win_rate ? `${(summary.win_rate * 100).toFixed(1)}%` : "0%"}
          </div>
        </div>
        <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-200 text-center">
          <div className="text-gray-500 text-sm font-medium mb-1">Avg Proj R:R</div>
          <div className="text-2xl font-bold text-gray-800">{summary.avg_projected_rr?.toFixed(2) || "0.00"}</div>
        </div>
        <div className="bg-white p-5 rounded-xl shadow-sm border border-gray-200 text-center">
          <div className="text-gray-500 text-sm font-medium mb-1">Avg Real R:R</div>
          <div className="text-2xl font-bold text-gray-800">{summary.avg_realized_rr?.toFixed(2) || "0.00"}</div>
        </div>
      </div>

      <RRScatterPlot trades={trades} />

      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden mt-8">
        <div className="px-6 py-4 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
          <h3 className="font-bold text-gray-800">Recent Closed Trades</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-white">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Symbol</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Closed At</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Entry</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Exit</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Real R:R</th>
                <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-8 text-center text-sm text-gray-500">
                    No trades closed yet.
                  </td>
                </tr>
              ) : (
                trades.map((t, idx) => (
                  <tr key={idx} className="hover:bg-gray-50">
                    <td className="px-6 py-3 whitespace-nowrap text-sm font-bold text-gray-900">{t.symbol}</td>
                    <td className="px-6 py-3 whitespace-nowrap text-sm text-gray-500">{new Date(t.exit_date).toLocaleDateString()}</td>
                    <td className="px-6 py-3 whitespace-nowrap text-sm text-right text-gray-600">₹{t.entry_price.toLocaleString()}</td>
                    <td className="px-6 py-3 whitespace-nowrap text-sm text-right text-gray-600">₹{t.exit_price.toLocaleString()}</td>
                    <td className="px-6 py-3 whitespace-nowrap text-right">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${t.realized_rr >= 1 ? 'bg-green-100 text-green-800' : t.realized_rr > 0 ? 'bg-amber-100 text-amber-800' : 'bg-red-100 text-red-800'}`}>
                        {t.realized_rr.toFixed(2)}
                      </span>
                    </td>
                    <td className="px-6 py-3 whitespace-nowrap text-center text-xs text-gray-500 uppercase">
                      {t.exit_reason.replace(/_/g, " ")}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
