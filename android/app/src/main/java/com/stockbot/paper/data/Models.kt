package com.stockbot.paper.data

import java.time.LocalDate

/*
 * Domain models. DRAFT: these are the future API contract (see docs/android/CONTRACT_DRAFT.md).
 * Money is in rupees (Double), percentages are in percent units (1.5 means 1.5%), dates are calendar dates.
 */

/** Registered verdict on the strategy. Stage 1 knows one value; it is always shown. */
enum class Verdict(val label: String) {
    NOT_DEMONSTRATED("not demonstrated"),
}

/** Fixed review marks shown against the account figures. */
data class ReviewMarks(
    /** Drawdown (percent below peak) at which the account is reviewed. */
    val drawdownReviewPct: Double,
    /** Closed trades needed before the first verdict can be given. */
    val closedTradesTarget: Int,
    val verdict: Verdict,
)

data class AccountSummary(
    /** Date of the data (last daily job). */
    val asOf: LocalDate,
    val startDate: LocalDate,
    val startingCapital: Double,
    val equity: Double,
    val cash: Double,
    /** Account return since start, percent. */
    val returnPct: Double,
    /** Nifty return over the same dates, percent. */
    val niftyReturnPct: Double,
    /** Current distance below the equity peak, percent (positive number). */
    val drawdownNowPct: Double,
    /** Worst distance below the equity peak so far, percent (positive number). */
    val drawdownWorstPct: Double,
    val closedTrades: Int,
)

/** One day of the equity curve. Nifty is rebased to the starting capital so both lines share one axis. */
data class EquityPoint(
    val date: LocalDate,
    val account: Double,
    val nifty: Double,
)

/** Everything the Account screen needs. */
data class AccountSnapshot(
    val summary: AccountSummary,
    val curve: List<EquityPoint>,
    val marks: ReviewMarks,
)

data class Ticket(
    val symbol: String,
    val sector: String,
    val shares: Int,
    /** Last close the suggestion is based on; the fill is at the next open. */
    val entryReference: Double,
    val stop: Double,
    /** Rupees lost if the stop is hit, before costs. */
    val riskRupees: Double,
)

enum class BlockReason { SECTOR_CAP }

/** A candidate that passed the signal but was blocked by a portfolio rule. */
data class BlockedItem(
    val symbol: String,
    val sector: String,
    val reason: BlockReason,
)

enum class Side { BUY, SELL }

/** An order that will fill at the next open. */
data class PendingFill(
    val symbol: String,
    val side: Side,
    val shares: Int,
    /** Short reason, for example "Stop reached". */
    val note: String,
)

data class TodayState(
    val asOf: LocalDate,
    val isSignalDay: Boolean,
    /** Risk per suggestion as a percent of equity (1.0 means 1%). */
    val riskPerTradePct: Double,
    val tickets: List<Ticket>,
    val blocked: List<BlockedItem>,
    val pendingFills: List<PendingFill>,
    /** Plain-language rule for the next signal day. */
    val nextSignalRule: String,
)

data class Position(
    val symbol: String,
    val shares: Int,
    val entryDate: LocalDate,
    val entryPrice: Double,
    val stop: Double,
    val lastClose: Double,
    /** (lastClose - entryPrice) * shares, rupees. */
    val unrealisedPnl: Double,
)

data class PositionsState(
    val asOf: LocalDate,
    val cash: Double,
    val positions: List<Position>,
)

enum class ExitReason(val label: String) {
    STOP_HIT("Stop hit"),
    GAP_THROUGH_STOP("Gap through stop"),
    TIME_EXIT("Time exit"),
    OTHER("Other"),
}

data class ClosedTrade(
    val symbol: String,
    val entryDate: LocalDate,
    val exitDate: LocalDate,
    val exitReason: ExitReason,
    /** Profit or loss after costs, rupees. */
    val netPnl: Double,
    /** Net P&L divided by the rupees risked at entry. */
    val netR: Double,
)

data class TradesState(
    val asOf: LocalDate,
    /** Newest exit first. */
    val trades: List<ClosedTrade>,
)

/** Summary figures for the Trades footer, computed from the trades. */
data class TradeStats(
    val count: Int,
    val wins: Int,
    /** Wins divided by trades, percent. */
    val winRatePct: Double,
    /** Gross profit divided by gross loss; null when there are no losing trades. */
    val profitFactor: Double?,
) {
    companion object {
        fun from(trades: List<ClosedTrade>): TradeStats {
            val wins = trades.count { it.netPnl > 0 }
            val grossWin = trades.filter { it.netPnl > 0 }.sumOf { it.netPnl }
            val grossLoss = -trades.filter { it.netPnl < 0 }.sumOf { it.netPnl }
            return TradeStats(
                count = trades.size,
                wins = wins,
                winRatePct = if (trades.isEmpty()) 0.0 else wins * 100.0 / trades.size,
                profitFactor = if (grossLoss > 0.0) grossWin / grossLoss else null,
            )
        }
    }
}
