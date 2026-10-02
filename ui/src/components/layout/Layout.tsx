import React from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../../api";
import { Activity, LayoutDashboard, List, Briefcase, BarChart2 } from "lucide-react";
import clsx from "clsx";

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: fetchHealth });

  const navItems = [
    { name: "Dashboard", path: "/", icon: LayoutDashboard },
    { name: "Watchlist", path: "/watchlist", icon: List },
    { name: "Portfolio", path: "/portfolio", icon: Briefcase },
    { name: "Analytics", path: "/analytics", icon: BarChart2 },
  ];

  const locked = health?.sha_locked && health?.tree_clean;

  return (
    <div className="flex h-screen overflow-hidden bg-gray-100">
      {/* Sidebar */}
      <div className="w-64 bg-gray-900 text-white flex flex-col">
        <div className="p-6 flex items-center space-x-3">
          <Activity className="w-8 h-8 text-blue-400" />
          <span className="text-xl font-bold tracking-tight">FInsight</span>
        </div>
        <nav className="flex-1 px-4 space-y-2 mt-4">
          {navItems.map((item) => {
            const active = location.pathname === item.path;
            const Icon = item.icon;
            return (
              <Link
                key={item.name}
                to={item.path}
                className={clsx(
                  "flex items-center space-x-3 px-4 py-3 rounded-md transition-colors",
                  active ? "bg-blue-600 text-white" : "text-gray-300 hover:bg-gray-800 hover:text-white"
                )}
              >
                <Icon className="w-5 h-5" />
                <span className="font-medium">{item.name}</span>
              </Link>
            );
          })}
        </nav>
        <div className="p-4 m-4 bg-gray-800 rounded-lg text-sm">
          <div className="flex items-center space-x-2 mb-2">
            <div className={clsx("w-3 h-3 rounded-full", locked ? "bg-green-500" : "bg-red-500")} />
            <span className="font-medium text-gray-200">System Lock</span>
          </div>
          <div className="text-gray-400 text-xs">
            {locked ? `Authorized: ${health?.authorized_sha}` : "Lock Broken / Not Authorized"}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b border-gray-200 h-16 flex items-center justify-between px-8">
          <h1 className="text-xl font-semibold text-gray-800">
            {navItems.find((n) => n.path === location.pathname)?.name || ""}
          </h1>
          <div className="flex items-center space-x-4 text-sm text-gray-500">
            {health?.last_pipeline_run && (
              <span>Last Run: {health.last_pipeline_run.run_date} ({health.last_pipeline_run.status})</span>
            )}
          </div>
        </header>
        <main className="flex-1 overflow-auto p-8">{children}</main>
      </div>
    </div>
  );
}
