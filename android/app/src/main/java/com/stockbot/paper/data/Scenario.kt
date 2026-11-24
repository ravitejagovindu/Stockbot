package com.stockbot.paper.data

import java.time.LocalDate

/** Mock data scenarios, selectable from the hidden debug menu. */
enum class Scenario(val label: String, val summary: String) {
    EMPTY("Empty", "Today's real state: cash only"),
    SIGNAL_DAY("Signal day", "3 suggestions, 12 blocked"),
    POSITIONS("Positions", "4 open, mixed P&L"),
    TRADES("Trades", "12 closed, 5 wins, profit factor 1.4"),
    DEEP_DRAWDOWN("Deep drawdown", "31% below peak, near the 35% mark"),
    STALE("Stale", "Data last updated 3 days ago"),
    ERROR("Error", "Every call fails"),
}

/** Thrown by the mock repository in the ERROR scenario. */
class MockRepositoryException : RuntimeException("Mock repository error")

/** Data older than this many days gets an "Updated N days ago" line. */
const val STALE_AFTER_DAYS = 3

/** Days since [asOf] when the data counts as stale, otherwise null. */
fun staleDays(asOf: LocalDate, today: LocalDate): Int? {
    val days = java.time.temporal.ChronoUnit.DAYS.between(asOf, today).toInt()
    return if (days >= STALE_AFTER_DAYS) days else null
}
