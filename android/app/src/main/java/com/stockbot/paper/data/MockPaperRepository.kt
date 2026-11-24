package com.stockbot.paper.data

import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.time.Clock
import java.time.DayOfWeek
import java.time.LocalDate
import kotlin.math.PI
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.roundToLong
import kotlin.math.sin

/**
 * Made-up data for stage 1. The scenario can be switched at any time; screens reload when it changes.
 * Dates are relative to the clock so the mock always looks current. [latencyMs] makes the loading state visible.
 */
class MockPaperRepository(
    initial: Scenario = Scenario.EMPTY,
    private val clock: Clock = Clock.systemDefaultZone(),
    private val latencyMs: Long = 450,
) : PaperRepository {

    private val _scenario = MutableStateFlow(initial)
    val scenario: StateFlow<Scenario> = _scenario

    fun select(scenario: Scenario) {
        _scenario.value = scenario
    }

    override val isSample: Boolean = true

    override suspend fun getToday(): TodayState = load { it.today }
    override suspend fun getAccount(): AccountSnapshot = load { it.account }
    override suspend fun getPositions(): PositionsState = load { it.positions }
    override suspend fun getTrades(): TradesState = load { it.trades }

    private suspend fun <T> load(pick: (MockData.Dataset) -> T): T {
        if (latencyMs > 0) delay(latencyMs)
        val scenario = _scenario.value
        if (scenario == Scenario.ERROR) throw MockRepositoryException()
        return pick(MockData.dataset(scenario, LocalDate.now(clock)))
    }
}

/** Builds the data for each scenario. Pure functions of (scenario, today), so tests can check the figures. */
object MockData {
    const val STARTING_CAPITAL = 200_000.0
    const val RISK_PER_TRADE_PCT = 1.0
    private const val RISK_BUDGET = STARTING_CAPITAL * RISK_PER_TRADE_PCT / 100.0
    private val MARKS = ReviewMarks(drawdownReviewPct = 35.0, closedTradesTarget = 30, verdict = Verdict.NOT_DEMONSTRATED)
    private const val NEXT_SIGNAL_RULE = "first trading day of next month"

    data class Dataset(
        val today: TodayState,
        val account: AccountSnapshot,
        val positions: PositionsState,
        val trades: TradesState,
    )

    fun lastWeekday(d: LocalDate): LocalDate {
        var x = d
        while (x.dayOfWeek == DayOfWeek.SATURDAY || x.dayOfWeek == DayOfWeek.SUNDAY) x = x.minusDays(1)
        return x
    }

    /** The last [count] weekdays ending at [end], oldest first. Holidays are ignored. */
    fun weekdays(end: LocalDate, count: Int): List<LocalDate> {
        val out = ArrayList<LocalDate>(count)
        var x = lastWeekday(end)
        while (out.size < count) {
            out.add(x)
            x = lastWeekday(x.minusDays(1))
        }
        return out.reversed()
    }

    fun dataset(scenario: Scenario, today: LocalDate): Dataset {
        val asOf = if (scenario == Scenario.STALE) today.minusDays(STALE_AFTER_DAYS.toLong()) else lastWeekday(today)
        return when (scenario) {
            Scenario.EMPTY, Scenario.ERROR -> empty(asOf)
            Scenario.SIGNAL_DAY -> signalDay(asOf)
            Scenario.POSITIONS, Scenario.STALE -> withPositions(asOf)
            Scenario.TRADES -> withTrades(asOf)
            Scenario.DEEP_DRAWDOWN -> deepDrawdown(asOf)
        }
    }

    // ----- scenarios -----

    private fun noSignalToday(asOf: LocalDate, pending: List<PendingFill> = emptyList()) = TodayState(
        asOf = asOf, isSignalDay = false, riskPerTradePct = RISK_PER_TRADE_PCT,
        tickets = emptyList(), blocked = emptyList(), pendingFills = pending, nextSignalRule = NEXT_SIGNAL_RULE,
    )

    private fun empty(asOf: LocalDate): Dataset {
        val days = weekdays(asOf, 14)
        val curve = curve(days, accountKeys = null, accountEnd = STARTING_CAPITAL, niftyEndPct = 0.6, accountNoise = 0.0, seed = 1)
        return Dataset(
            today = noSignalToday(asOf),
            account = AccountSnapshot(summary(asOf, days.first(), STARTING_CAPITAL, STARTING_CAPITAL, curve, closed = 0), curve, MARKS),
            positions = PositionsState(asOf, STARTING_CAPITAL, emptyList()),
            trades = TradesState(asOf, emptyList()),
        )
    }

    private fun signalDay(asOf: LocalDate): Dataset {
        val base = empty(asOf)
        val tickets = listOf(
            ticket("TCS", "IT", 3985.00, 3812.00),
            ticket("HDFCBANK", "Financials", 1642.30, 1589.00),
            ticket("ITC", "FMCG", 468.40, 448.60),
        )
        val blocked = listOf(
            "ICICIBANK" to "Financials", "AXISBANK" to "Financials", "KOTAKBANK" to "Financials", "SBIN" to "Financials",
            "BAJFINANCE" to "Financials", "INFY" to "IT", "HCLTECH" to "IT", "WIPRO" to "IT", "TECHM" to "IT",
            "HINDUNILVR" to "FMCG", "NESTLEIND" to "FMCG", "BRITANNIA" to "FMCG",
        ).map { (s, sec) -> BlockedItem(s, sec, BlockReason.SECTOR_CAP) }
        return base.copy(
            today = TodayState(
                asOf = asOf, isSignalDay = true, riskPerTradePct = RISK_PER_TRADE_PCT,
                tickets = tickets, blocked = blocked, pendingFills = emptyList(), nextSignalRule = NEXT_SIGNAL_RULE,
            ),
        )
    }

    private fun ticket(symbol: String, sector: String, entry: Double, stop: Double): Ticket {
        val perShare = entry - stop
        val shares = floor(RISK_BUDGET / perShare).toInt()
        return Ticket(symbol, sector, shares, entry, stop, riskRupees = (shares * perShare).roundToLong().toDouble())
    }

    private fun withPositions(asOf: LocalDate): Dataset {
        val days = weekdays(asOf, 40)
        fun back(n: Int) = days[days.size - 1 - n]
        fun pos(symbol: String, shares: Int, entryBack: Int, entry: Double, stop: Double, last: Double) =
            Position(symbol, shares, back(entryBack), entry, stop, last, unrealisedPnl = round2(shares * (last - entry)))
        val positions = listOf(
            pos("INFY", 25, 18, 1520.00, 1468.00, 1575.40),
            pos("SBIN", 55, 12, 812.00, 776.00, 796.20),
            pos("LT", 11, 9, 3720.00, 3590.00, 3801.00),
            pos("MARUTI", 3, 4, 12480.00, 12050.00, 12040.00),
        )
        val cash = STARTING_CAPITAL - positions.sumOf { it.shares * it.entryPrice }
        val equity = cash + positions.sumOf { it.shares * it.lastClose }
        val curve = curve(days, accountKeys = null, accountEnd = equity, niftyEndPct = 1.1, accountNoise = 0.004, seed = 3)
        return Dataset(
            today = noSignalToday(asOf, listOf(PendingFill("MARUTI", Side.SELL, 3, "Stop reached"))),
            account = AccountSnapshot(summary(asOf, days.first(), STARTING_CAPITAL, equity, curve, closed = 0, cash = cash), curve, MARKS),
            positions = PositionsState(asOf, cash, positions),
            trades = TradesState(asOf, emptyList()),
        )
    }

    /** (symbol, sessions since exit, sessions held, reason, net P&L). Newest first. Wins 19,600, losses 14,000: profit factor 1.4. */
    private data class TradeRow(val symbol: String, val exitBack: Int, val held: Int, val reason: ExitReason, val pnl: Double)

    private val TRADE_ROWS = listOf(
        TradeRow("WIPRO", 4, 22, ExitReason.TIME_EXIT, 3900.0),
        TradeRow("BAJFINANCE", 9, 6, ExitReason.STOP_HIT, -2100.0),
        TradeRow("TITAN", 14, 31, ExitReason.TIME_EXIT, 6200.0),
        TradeRow("ONGC", 19, 8, ExitReason.STOP_HIT, -2000.0),
        TradeRow("HCLTECH", 24, 5, ExitReason.GAP_THROUGH_STOP, -2300.0),
        TradeRow("CIPLA", 31, 27, ExitReason.TIME_EXIT, 2800.0),
        TradeRow("AXISBANK", 37, 10, ExitReason.STOP_HIT, -1800.0),
        TradeRow("NTPC", 44, 29, ExitReason.TIME_EXIT, 5100.0),
        TradeRow("TATASTEEL", 50, 7, ExitReason.STOP_HIT, -2200.0),
        TradeRow("ASIANPAINT", 57, 12, ExitReason.STOP_HIT, -1900.0),
        TradeRow("HINDALCO", 63, 33, ExitReason.TIME_EXIT, 1600.0),
        TradeRow("M&M", 70, 9, ExitReason.STOP_HIT, -1700.0),
    )

    private fun closedTrades(days: List<LocalDate>): List<ClosedTrade> = TRADE_ROWS.map { r ->
        ClosedTrade(
            symbol = r.symbol,
            entryDate = days[days.size - 1 - r.exitBack - r.held],
            exitDate = days[days.size - 1 - r.exitBack],
            exitReason = r.reason,
            netPnl = r.pnl,
            netR = r.pnl / RISK_BUDGET,
        )
    }

    private fun withTrades(asOf: LocalDate): Dataset {
        val days = weekdays(asOf, 120)
        val trades = closedTrades(days)
        val equity = STARTING_CAPITAL + trades.sumOf { it.netPnl }
        val curve = curve(days, accountKeys = null, accountEnd = equity, niftyEndPct = 3.4, accountNoise = 0.006, seed = 5)
        return Dataset(
            today = noSignalToday(asOf),
            account = AccountSnapshot(summary(asOf, days.first(), STARTING_CAPITAL, equity, curve, closed = trades.size), curve, MARKS),
            positions = PositionsState(asOf, equity, emptyList()),
            trades = TradesState(asOf, trades),
        )
    }

    private fun deepDrawdown(asOf: LocalDate): Dataset {
        val days = weekdays(asOf, 160)
        val trades = closedTrades(weekdays(asOf, 160))
        val peak = 260_000.0
        val equity = peak * 0.69
        // Straight segments with no noise, so the peak and the 31% figure are exact.
        // Key fractions are snapped to real days so the peak and the trough are actual points on the curve.
        fun onDay(f: Double) = Math.round(f * (days.size - 1)).toDouble() / (days.size - 1)
        val keys = listOf(0.0 to STARTING_CAPITAL, onDay(0.35) to peak, onDay(0.8) to peak * 0.675, 1.0 to equity)
        val curve = curve(days, accountKeys = keys, accountEnd = equity, niftyEndPct = 2.4, accountNoise = 0.0, seed = 7)
        return Dataset(
            today = noSignalToday(asOf),
            account = AccountSnapshot(summary(asOf, days.first(), STARTING_CAPITAL, equity, curve, closed = trades.size), curve, MARKS),
            positions = PositionsState(asOf, equity, emptyList()),
            trades = TradesState(asOf, trades),
        )
    }

    // ----- helpers -----

    private fun round2(v: Double) = (v * 100).roundToLong() / 100.0

    private fun summary(
        asOf: LocalDate, start: LocalDate, startCap: Double, equity: Double, curve: List<EquityPoint>, closed: Int, cash: Double = equity,
    ): AccountSummary {
        var peak = curve.first().account
        var worst = 0.0
        for (p in curve) {
            peak = max(peak, p.account)
            worst = max(worst, (peak - p.account) / peak * 100.0)
        }
        val now = (peak - curve.last().account) / peak * 100.0
        return AccountSummary(
            asOf = asOf, startDate = start, startingCapital = startCap, equity = equity, cash = cash,
            returnPct = (equity / startCap - 1.0) * 100.0,
            niftyReturnPct = (curve.last().nifty / startCap - 1.0) * 100.0,
            drawdownNowPct = now, drawdownWorstPct = max(worst, now), closedTrades = closed,
        )
    }

    /** Deterministic curves: the account follows [accountKeys] (or a straight line to [accountEnd]) plus noise; Nifty drifts to [niftyEndPct]. */
    private fun curve(
        days: List<LocalDate>, accountKeys: List<Pair<Double, Double>>?, accountEnd: Double, niftyEndPct: Double, accountNoise: Double, seed: Int,
    ): List<EquityPoint> {
        val n = days.size
        return days.mapIndexed { i, date ->
            val f = if (n == 1) 1.0 else i.toDouble() / (n - 1)
            val window = sin(PI * f)
            val account = when {
                i == n - 1 -> accountEnd
                accountKeys != null -> interpolate(accountKeys, f)
                else -> STARTING_CAPITAL + (accountEnd - STARTING_CAPITAL) * f + STARTING_CAPITAL * accountNoise * sin(i * 0.28 + seed) * window
            }
            val nifty = if (i == n - 1) STARTING_CAPITAL * (1 + niftyEndPct / 100.0)
            else STARTING_CAPITAL * (1 + niftyEndPct / 100.0 * f) + STARTING_CAPITAL * 0.005 * sin(i * 0.19 + seed * 2.0) * window
            EquityPoint(date, account, nifty)
        }
    }

    private fun interpolate(keys: List<Pair<Double, Double>>, f: Double): Double {
        for (k in 1 until keys.size) {
            val (f0, v0) = keys[k - 1]
            val (f1, v1) = keys[k]
            if (f <= f1) return v0 + (v1 - v0) * ((f - f0) / (f1 - f0))
        }
        return keys.last().second
    }
}
