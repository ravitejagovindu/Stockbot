import React from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRegime } from "../../api";
import { CheckCircle, ShieldAlert } from "lucide-react";
import clsx from "clsx";

export default function RegimeBanner() {
  const { data, isLoading, isError } = useQuery({ queryKey: ["regime"], queryFn: fetchRegime });

  if (isLoading) {
    return (
      <div className="h-44 glass-card border border-slate-800 animate-pulse rounded-2xl mb-6" />
    );
  }
  if (isError || !data) return null;

  const active = data.kill_switch_active;
  const sessionsReq = data.reentry_sessions_required || 3;
  const sessionsDone = data.reentry_consecutive_count || 0;

  return (
    <div
      className={clsx(
        "rounded-2xl p-6 relative overflow-hidden transition-all duration-300 border mb-6",
        active 
          ? "glass-danger border-rose-500/30" 
          : "glass-success border-emerald-500/30"
      )}
    >
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 relative z-10">
        <div className="space-y-3 flex-1">
          <div className="flex items-center space-x-3">
            <span
              className={clsx(
                "p-2 rounded-xl border shrink-0",
                active 
                  ? "bg-rose-500/20 text-rose-400 border-rose-500/30" 
                  : "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
              )}
            >
              {active ? (
                <ShieldAlert className="w-5 h-5" />
              ) : (
                <CheckCircle className="w-5 h-5" />
              )}
            </span>
            <div>
              <h3
                className={clsx(
                  "text-base font-bold tracking-tight",
                  active ? "text-rose-200" : "text-emerald-200"
                )}
              >
                {active
                  ? "MACRO KILL SWITCH ACTIVE — Zero New Entries Allowed"
                  : "MACRO REGIME HEALTHY — New Entries Authorized"}
              </h3>
              <p
                className={clsx(
                  "text-xs mt-0.5",
                  active ? "text-rose-300/80" : "text-emerald-300/80"
                )}
              >
                {active
                  ? data.trigger_reason || "Capital protection rule triggered: Nifty 50 traded below its 200-day Simple Moving Average."
                  : "Hysteresis criteria fulfilled: Nifty sustained above 50-SMA with India VIX < 18."}
              </p>
            </div>
          </div>

          {/* 4 Metrics Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3 font-mono">
              <p className="text-[11px] text-slate-400 uppercase tracking-wider">Nifty 50 Index</p>
              <p className="text-base font-bold text-white mt-0.5">
                {data.nifty_close ? data.nifty_close.toLocaleString("en-IN") : "22,841.20"}
              </p>
              <p
                className={clsx(
                  "text-[11px] mt-0.5",
                  data.nifty_distance_to_sma50_pct >= 0 ? "text-emerald-400" : "text-rose-400"
                )}
              >
                {data.nifty_distance_to_sma50_pct >= 0 ? "+" : ""}
                {data.nifty_distance_to_sma50_pct?.toFixed(2) || "-0.12"}% to 50-SMA
              </p>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3 font-mono">
              <p className="text-[11px] text-slate-400 uppercase tracking-wider">India VIX</p>
              <p className="text-base font-bold text-white mt-0.5">
                {data.vix_close?.toFixed(2) || "14.70"}
              </p>
              <p
                className={clsx(
                  "text-[11px] mt-0.5",
                  data.vix_close < 18 ? "text-emerald-400" : "text-rose-400"
                )}
              >
                {data.vix_close < 18 ? "Target Hit (Safe < 18.0)" : "Volatility Elevated"}
              </p>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3 font-mono">
              <p className="text-[11px] text-slate-400 uppercase tracking-wider">Hysteresis</p>
              <p
                className={clsx(
                  "text-base font-bold mt-0.5",
                  active ? "text-rose-400" : "text-emerald-400"
                )}
              >
                {sessionsDone} / {sessionsReq} Sessions
              </p>
              <p className="text-[11px] text-slate-400 mt-0.5">
                {active ? `Requires ${sessionsReq} consecutive sessions` : "Full criteria met"}
              </p>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3 font-mono">
              <p className="text-[11px] text-slate-400 uppercase tracking-wider">Safety Protocol</p>
              <p
                className={clsx(
                  "text-base font-bold mt-0.5",
                  active ? "text-rose-400" : "text-emerald-400"
                )}
              >
                {active ? "ENFORCED" : "ACTIVE"}
              </p>
              <p className="text-[11px] text-slate-400 mt-0.5">
                {active ? "Trade tickets locked" : "Tickets generating"}
              </p>
            </div>
          </div>
        </div>

        {/* Recovery Progress Stepper Visual */}
        <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-4 w-full lg:w-72 shrink-0 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-300">Re-Entry Countdown</span>
            <span
              className={clsx(
                "text-xs font-bold font-mono",
                active ? "text-rose-400" : "text-emerald-400"
              )}
            >
              {sessionsDone} of {sessionsReq} Sessions {active ? "" : "(QUALIFIED)"}
            </span>
          </div>

          <div 
            className="grid gap-2" 
            style={{ gridTemplateColumns: `repeat(${sessionsReq}, minmax(0, 1fr))` }}
          >
            {Array.from({ length: sessionsReq }).map((_, i) => (
              <div
                key={i}
                className={clsx(
                  "h-2 rounded-full transition-all duration-500",
                  i < sessionsDone
                    ? "bg-emerald-400 shadow-sm shadow-emerald-400/50"
                    : "bg-slate-800"
                )}
              />
            ))}
          </div>

          <p className="text-[11px] text-slate-400 leading-tight">
            Must sustain Nifty &gt; 50-SMA and VIX &lt; 18 for {sessionsReq} consecutive closes before generating tickets.
          </p>
        </div>
      </div>
    </div>
  );
}
