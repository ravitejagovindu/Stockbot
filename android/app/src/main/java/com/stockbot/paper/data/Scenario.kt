package com.stockbot.paper.data

/** Mock data scenarios, selectable from the hidden debug menu. Each one is a set of example JSON files (docs/android/contract/examples). */
enum class Scenario(val label: String, val summary: String, val fileSuffix: String) {
    EMPTY("Empty", "Today's real state: cash only", "empty"),
    SIGNAL_DAY("Signal day", "3 suggestions, 12 blocked", "signal_day"),
    POSITIONS("Positions", "4 open, mixed P&L", "positions"),
    TRADES("Trades", "12 closed (1 flagged), 5 wins, profit factor 1.62", "trades"),
    DEEP_DRAWDOWN("Deep drawdown", "31% below peak, near the 35% mark", "deep_drawdown"),
    STALE("Stale", "Data two trading days behind", "stale"),
    ERROR("Error", "Every call fails (not ready)", "not_ready"),
}
