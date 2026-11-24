package com.stockbot.paper

import com.stockbot.paper.data.BlockReason
import com.stockbot.paper.data.MockPaperRepository
import com.stockbot.paper.data.Scenario
import com.stockbot.paper.data.Side
import com.stockbot.paper.data.TradeStats
import com.stockbot.paper.data.Verdict
import com.stockbot.paper.data.staleDays
import com.stockbot.paper.theme.Palette
import com.stockbot.paper.ui.ScreenLoader
import com.stockbot.paper.ui.ScreenState
import com.stockbot.paper.ui.drawdownColor
import com.stockbot.paper.ui.drawdownFraction
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import java.time.Clock
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import org.junit.Test

/** Each scenario, read through the repository and the screen loader, gives the state the screens expect. */
class ScenarioStateTest {
    private val clock = Clock.fixed(Instant.parse("2026-11-24T10:00:00Z"), ZoneOffset.UTC)
    private val today: LocalDate = LocalDate.of(2026, 11, 24)

    private fun loader(s: Scenario) = ScreenLoader(MockPaperRepository(s, clock, latencyMs = 0))

    private inline fun <reified T> content(state: ScreenState<*>): T {
        val data = when (state) {
            is ScreenState.Content<*> -> state.data
            is ScreenState.Empty<*> -> state.data
            else -> error("expected data, got $state")
        }
        return data as T
    }

    @Test fun emptyIsTodaysRealState() = runBlocking {
        val l = loader(Scenario.EMPTY)
        val todayState = l.today()
        assertTrue(todayState is ScreenState.Empty)
        val t = content<com.stockbot.paper.data.TodayState>(todayState)
        assertTrue(!t.isSignalDay && t.tickets.isEmpty() && t.pendingFills.isEmpty())
        assertEquals("first trading day of next month", t.nextSignalRule)

        val account = l.account()
        assertTrue(account is ScreenState.Content)
        val a = content<com.stockbot.paper.data.AccountSnapshot>(account)
        assertEquals(200_000.0, a.summary.equity, 0.0)
        assertEquals(200_000.0, a.summary.cash, 0.0)
        assertEquals(0, a.summary.closedTrades)
        assertEquals(0.0, a.summary.drawdownNowPct, 0.0)
        assertEquals(setOf(200_000.0), a.curve.map { it.account }.toSet())
        assertTrue(a.curve.size >= 2)
        assertEquals(Verdict.NOT_DEMONSTRATED, a.marks.verdict)

        val p = l.positions()
        assertTrue(p is ScreenState.Empty)
        assertEquals(200_000.0, content<com.stockbot.paper.data.PositionsState>(p).cash, 0.0)
        assertTrue(l.trades() is ScreenState.Empty)
    }

    @Test fun signalDayHasThreeTicketsAndTwelveBlocked() = runBlocking {
        val state = loader(Scenario.SIGNAL_DAY).today()
        assertTrue(state is ScreenState.Content)
        val t = content<com.stockbot.paper.data.TodayState>(state)
        assertTrue(t.isSignalDay)
        assertEquals(3, t.tickets.size)
        assertEquals(12, t.blocked.size)
        assertTrue(t.blocked.all { it.reason == BlockReason.SECTOR_CAP })
        assertEquals(1.0, t.riskPerTradePct, 0.0)
        // Risk is about 1% of 200,000 each and never above it.
        t.tickets.forEach {
            assertTrue(it.shares > 0)
            assertTrue(it.stop < it.entryReference)
            assertTrue("${it.symbol} risk ${it.riskRupees}", it.riskRupees in 1_800.0..2_000.0)
        }
    }

    @Test fun positionsHaveFourOpenWithMixedPnl() = runBlocking {
        val l = loader(Scenario.POSITIONS)
        val state = l.positions()
        assertTrue(state is ScreenState.Content)
        val p = content<com.stockbot.paper.data.PositionsState>(state)
        assertEquals(4, p.positions.size)
        assertTrue(p.positions.any { it.unrealisedPnl > 0 })
        assertTrue(p.positions.any { it.unrealisedPnl < 0 })
        p.positions.forEach { assertEquals(it.shares * (it.lastClose - it.entryPrice), it.unrealisedPnl, 0.01) }
        // Equity = cash + market value, and the Account screen agrees.
        val a = content<com.stockbot.paper.data.AccountSnapshot>(l.account())
        assertEquals(p.cash + p.positions.sumOf { it.shares * it.lastClose }, a.summary.equity, 0.01)
        assertEquals(p.cash, a.summary.cash, 0.0)
        // One position has touched its stop and is waiting to be sold at the next open.
        val pending = content<com.stockbot.paper.data.TodayState>(l.today()).pendingFills
        assertEquals(1, pending.size)
        assertEquals(Side.SELL, pending[0].side)
    }

    @Test fun tradesHaveTwelveClosedFiveWinsProfitFactorOnePointFour() = runBlocking {
        val l = loader(Scenario.TRADES)
        val state = l.trades()
        assertTrue(state is ScreenState.Content)
        val t = content<com.stockbot.paper.data.TradesState>(state)
        assertEquals(12, t.trades.size)
        val stats = TradeStats.from(t.trades)
        assertEquals(5, stats.wins)
        assertEquals(1.4, stats.profitFactor!!, 1e-9)
        assertEquals(41.67, stats.winRatePct, 0.01)
        // Newest first, and each trade enters before it exits.
        assertEquals(t.trades.sortedByDescending { it.exitDate }.map { it.symbol }, t.trades.map { it.symbol })
        t.trades.forEach { assertTrue(it.entryDate < it.exitDate) }
        val a = content<com.stockbot.paper.data.AccountSnapshot>(l.account())
        assertEquals(12, a.summary.closedTrades)
        assertEquals(200_000.0 + t.trades.sumOf { it.netPnl }, a.summary.equity, 0.01)
    }

    @Test fun deepDrawdownIsThirtyOnePercentBelowPeakAndWarns() = runBlocking {
        val a = content<com.stockbot.paper.data.AccountSnapshot>(loader(Scenario.DEEP_DRAWDOWN).account())
        assertEquals(31.0, a.summary.drawdownNowPct, 0.01)
        assertTrue(a.summary.drawdownWorstPct >= a.summary.drawdownNowPct)
        assertTrue(a.summary.drawdownWorstPct < 35.0)
        val peak = a.curve.maxOf { it.account }
        assertEquals(0.31, (peak - a.summary.equity) / peak, 0.0001)
        assertEquals(35.0, a.marks.drawdownReviewPct, 0.0)
        val fraction = drawdownFraction(a.summary.drawdownNowPct, a.marks.drawdownReviewPct)
        assertEquals(0.886f, fraction, 0.001f)
        assertEquals(Palette.Light.warning, drawdownColor(fraction, Palette.Light))
        assertEquals(Palette.Dark.warning, drawdownColor(fraction, Palette.Dark))
    }

    @Test fun drawdownBarColoursByShareOfTheMark() {
        assertEquals(Palette.Light.accent, drawdownColor(drawdownFraction(10.0, 35.0), Palette.Light))
        assertEquals(Palette.Light.warning, drawdownColor(drawdownFraction(30.0, 35.0), Palette.Light))
        assertEquals(Palette.Light.loss, drawdownColor(drawdownFraction(36.0, 35.0), Palette.Light))
    }

    @Test fun staleDataIsThreeDaysOld() = runBlocking {
        val l = loader(Scenario.STALE)
        val a = content<com.stockbot.paper.data.AccountSnapshot>(l.account())
        assertEquals(today.minusDays(3), a.summary.asOf)
        assertEquals(3, staleDays(a.summary.asOf, today))
        assertEquals(3, staleDays(content<com.stockbot.paper.data.PositionsState>(l.positions()).asOf, today))
        assertEquals(3, staleDays(content<com.stockbot.paper.data.TodayState>(l.today()).asOf, today))
    }

    @Test fun otherScenariosAreNotStale() = runBlocking {
        for (s in Scenario.entries.filter { it != Scenario.STALE && it != Scenario.ERROR }) {
            val a = content<com.stockbot.paper.data.AccountSnapshot>(loader(s).account())
            assertNull("$s", staleDays(a.summary.asOf, today))
        }
    }

    @Test fun errorScenarioFailsEveryScreenCalmly() = runBlocking {
        val l = loader(Scenario.ERROR)
        val expected = ScreenState.Error(ScreenLoader.ERROR_MESSAGE)
        assertEquals(expected, l.today())
        assertEquals(expected, l.account())
        assertEquals(expected, l.positions())
        assertEquals(expected, l.trades())
        assertTrue(!ScreenLoader.ERROR_MESSAGE.contains("!") && !ScreenLoader.ERROR_MESSAGE.lowercase().contains("please"))
    }

    @Test fun switchingScenarioChangesWhatTheRepositoryReturns() = runBlocking {
        val repo = MockPaperRepository(Scenario.EMPTY, clock, latencyMs = 0)
        val l = ScreenLoader(repo)
        assertTrue(l.trades() is ScreenState.Empty)
        repo.select(Scenario.TRADES)
        assertTrue(l.trades() is ScreenState.Content)
        repo.select(Scenario.ERROR)
        assertTrue(l.trades() is ScreenState.Error)
        assertTrue(repo.isSample)
    }

    @Test fun mockCurvesStartAtCapitalAndEndAtEquity() = runBlocking {
        for (s in Scenario.entries.filter { it != Scenario.ERROR }) {
            val a = content<com.stockbot.paper.data.AccountSnapshot>(loader(s).account())
            assertEquals("$s start", 200_000.0, a.curve.first().account, 0.0)
            assertEquals("$s end", a.summary.equity, a.curve.last().account, 0.01)
            assertEquals("$s nifty", a.summary.niftyReturnPct, (a.curve.last().nifty / 200_000.0 - 1) * 100, 0.001)
            assertTrue("$s dates", a.curve.zipWithNext().all { (x, y) -> x.date < y.date })
        }
    }
}
