import React from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth, fetchWatchlist, fetchPortfolio, fetchAnalytics } from "../../api";
import { 
  LayoutDashboard, 
  List, 
  Briefcase, 
  BarChart2, 
  ShieldCheck, 
  Clock, 
  AlertTriangle 
} from "lucide-react";
import clsx from "clsx";

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const { data: watchlist } = useQuery({ queryKey: ["watchlist"], queryFn: () => fetchWatchlist() });
  const { data: portfolio } = useQuery({ queryKey: ["portfolio"], queryFn: fetchPortfolio });
  const { data: analytics } = useQuery({ queryKey: ["analytics"], queryFn: () => fetchAnalytics(20) });

  const decaySignal = analytics?.summary?.decay_signal;

  const navItems = [
    { 
      name: "Command Cockpit", 
      path: "/", 
      icon: LayoutDashboard,
      badge: null
    },
    { 
      name: "Trade Tickets", 
      path: "/watchlist", 
      icon: List,
      badge: watchlist?.approved_count !== undefined ? `${watchlist.approved_count} Approved` : null,
      badgeColor: (watchlist?.approved_count || 0) > 0 
        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" 
        : "bg-slate-800 text-slate-400 border-slate-700"
    },
    { 
      name: "Live Portfolio", 
      path: "/portfolio", 
      icon: Briefcase,
      badge: portfolio?.summary?.open_positions !== undefined 
        ? `${portfolio.summary.open_positions}/${portfolio.summary.max_positions || 12}` 
        : null,
      badgeColor: "bg-slate-800 text-slate-300 border-slate-700"
    },
    { 
      name: "Alpha & Decay", 
      path: "/analytics", 
      icon: BarChart2,
      badge: decaySignal ? (decaySignal === "HEALTHY" ? "α OK" : decaySignal) : "α OK",
      badgeColor: decaySignal === "CRITICAL"
        ? "bg-rose-500/20 text-rose-300 border-rose-500/30"
        : decaySignal === "WARNING"
        ? "bg-amber-500/20 text-amber-300 border-amber-500/30"
        : "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
    },
  ];

  const locked = Boolean(health?.sha_locked && health?.tree_clean);
  const shortSha = health?.authorized_sha ? `#${health.authorized_sha.slice(0, 7)}` : "VERIFIED";

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#080c14] text-slate-100">
      {/* Top Global Compliance & System Lock Header */}
      <header className="h-16 border-b border-slate-800/80 bg-[#0d131f]/90 sticky top-0 z-50 px-6 flex items-center justify-between backdrop-blur-md shrink-0">
        <div className="flex items-center space-x-6">
          {/* Logo & Brand */}
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-blue-500/20">
              <BarChart2 className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="text-base font-bold tracking-tight text-white flex items-center gap-1.5">
                FinBot
              </span>
              <p className="text-[11px] text-slate-400 font-mono">Quant Trading Terminal</p>
            </div>
          </div>
        </div>

        {/* Right Status: Git Lock & EOD Clock */}
        <div className="flex items-center space-x-4">
          {/* Git Lock Badge */}
          <div 
            className={clsx(
              "flex items-center space-x-2 px-3 py-1.5 rounded-lg border text-xs font-mono font-medium",
              locked 
                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" 
                : "bg-rose-500/10 border-rose-500/20 text-rose-300"
            )}
          >
            {locked ? (
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
            )}
            <span>
              {locked 
                ? `Git-SHA: ${shortSha} (LOCKED)` 
                : health?.current_sha 
                ? `Git-SHA: #${health.current_sha.slice(0, 7)} (DIRTY TREE)` 
                : "System Lock: Broken / Unverified"}
            </span>
          </div>

          {/* EOD Pipeline Status */}
          <div className="hidden lg:flex items-center space-x-2 text-xs text-slate-400 bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800 font-mono">
            <Clock className="w-3.5 h-3.5 text-blue-400" />
            <span>
              EOD Run: <strong className="text-slate-200">17:00 IST</strong>
            </span>
            <span className="text-emerald-400 font-medium">
              ● {health?.last_pipeline_run?.status || "Complete"}
            </span>
          </div>
        </div>
      </header>

      {/* Main Layout Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Navigation Sidebar */}
        <aside className="w-64 bg-[#0a0f1d] border-r border-slate-800/80 p-4 flex flex-col justify-between shrink-0">
          <div className="space-y-6">
            {/* Terminal Workspaces */}
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 px-3 mb-2 font-mono">
                Terminal Workspaces
              </p>
              <nav className="space-y-1">
                {navItems.map((item) => {
                  const active = location.pathname === item.path;
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.name}
                      to={item.path}
                      className={clsx(
                        "w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all border",
                        active 
                          ? "bg-blue-600/15 text-blue-400 border-blue-500/30 glow-blue" 
                          : "text-slate-300 hover:text-white hover:bg-slate-800/60 border-transparent"
                      )}
                    >
                      <div className="flex items-center space-x-3">
                        <Icon className={clsx("w-4 h-4", active ? "text-blue-400" : "text-slate-400")} />
                        <span>{item.name}</span>
                      </div>
                      {item.badge ? (
                        <span className={clsx("text-[10px] font-mono px-2 py-0.5 rounded-full border", item.badgeColor)}>
                          {item.badge}
                        </span>
                      ) : active ? (
                        <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                      ) : null}
                    </Link>
                  );
                })}
              </nav>
            </div>

          </div>

          {/* User / Operator Card */}
          <div className="pt-4 border-t border-slate-800/80">
            <div className="flex items-center justify-between p-2 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="flex items-center space-x-2.5">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center font-bold text-xs text-white">
                  R
                </div>
                <div className="overflow-hidden">
                  <p className="text-xs font-semibold text-slate-200 truncate">Ravi</p>
                </div>
              </div>
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400" title="Terminal Active" />
            </div>
          </div>
        </aside>

        {/* Dynamic Content Body */}
        <main className="flex-1 overflow-y-auto p-8 bg-[#080c14]">
          {children}
        </main>
      </div>
    </div>
  );
}
