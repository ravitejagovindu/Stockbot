package com.stockbot.paper

import com.stockbot.paper.data.AccountSnapshot
import com.stockbot.paper.data.ApiException
import com.stockbot.paper.data.BlockReason
import com.stockbot.paper.data.ErrorCode
import com.stockbot.paper.data.Freshness
import com.stockbot.paper.data.MockPaperRepository
import com.stockbot.paper.data.PositionsState
import com.stockbot.paper.data.Scenario
import com.stockbot.paper.data.Side
import com.stockbot.paper.data.TodayState
import com.stockbot.paper.data.TradesState
import com.stockbot.paper.theme.Palette
import com.stockbot.paper.ui.ScreenLoader
import com.stockbot.paper.ui.ScreenState
import com.stockbot.paper.ui.drawdownColor
import com.stockbot.paper.ui.drawdownFraction
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** Each scenario, read through the repository (which parses the example JSON files) and the screen loader, gives the state the screens expect. */
class ScenarioStateTest {
    private fun repo(s: Scenario) = MockPaperRepository(TestExamples.source, s, latencyMs = 0)
    private fun loader(s: Scenario) = ScreenLoader(repo(s))

    private fun <T> data(state: ScreenState<T>): T = when (state) {
        is ScreenState.Content -> state.data
        is ScreenState.Empty -> state.data
        else -> error("expected data, got $state")
    }

    @Test fun emptyIsTodaysRealState() = runBlocking {
        val l = loader(Scenario.EMPTY)
        val todayState = l.today()
        assertTrue(todayState is ScreenState.Empty)
        val t: TodayState = data(todayState)
        assertTrue(!t.isSignalDay && t.tickets.isEmpty() && t.pendingFills.isEmpty())
        assertEquals("first trading day of next month", t.nextSignalRule)

        val account = l.account()
        assertTrue(account is ScreenState.Content)
        val a: AccountSnapshot = data(account)
        assertEquals(20_000_000L, a.summary.equityPaise)
        assertEquals(20_000_000L, a.summary.cashPaise)
        assertEquals(0, a.summary.closedTrades)
        assertEquals(0.0, a.summary.drawdownNowPct, 0.0)
        assertEquals(setOf(20_000_000L), a.curve.map { it.accountPaise }.toSet())
        assertTrue(a.curve.size >= 2)
        assertEquals("not demonstrated", a.marks.verdict)

        val p = l.positions()
        assertTrue(p is ScreenState.Empty)
        assertEquals(20_000_000L, data(p).cashPaise)
        assertTrue(l.trades() is ScreenState.Empty)
        assertNull(Freshness.daysBehind(a))
    }

    @Test fun signalDayHasThreeTicketsAndTwelveBlocked() = runBlocking {
        val state = loader(Scenario.SIGNAL_DAY).today()
        assertTrue(state is ScreenState.Content)
        val t = data(state)
        assertTrue(t.isSignalDay)
        assertEquals(3, t.tickets.size)
        assertEquals(12, t.blocked.size)
        assertTrue(t.blocked.all { it.reason == BlockReason.SECTOR_CAP })
    }

    @Test fun positionsHaveFourOpenWithMixedPnlAndOnePendingExit() = runBlocking {
        val l = loader(Scenario.POSITIONS)
        val state = l.positions()
        assertTrue(state is ScreenState.Content)
        val p: PositionsState = data(state)
        assertEquals(4, p.positions.size)
        assertTrue(p.positions.any { it.unrealisedPnlPaise > 0 })
        assertTrue(p.positions.any { it.unrealisedPnlPaise < 0 })
        val a = data(l.account())
        assertEquals(p.cashPaise + p.positions.sumOf { it.shares * it.lastClosePaise }, a.summary.equityPaise)
        val pending = data(l.today()).pendingFills
        assertEquals(1, pending.size)
        assertEquals(Side.SELL, pending[0].side)
    }

    @Test fun tradesHaveTwelveClosedOneFlaggedFiveWins() = runBlocking {
        val l = loader(Scenario.TRADES)
        val state = l.trades()
        assertTrue(state is ScreenState.Content)
        val t: TradesState = data(state)
        assertEquals(12, t.trades.size)
        assertEquals(5, t.stats.wins)
        assertEquals(1, t.stats.excludedFromStats)
        assertEquals(1.62, t.stats.profitFactor!!, 1e-9)
        assertEquals(12, data(l.account()).summary.closedTrades)
    }

    @Test fun deepDrawdownIsThirtyOnePercentBelowPeakAndWarns() = runBlocking {
        val a = data(loader(Scenario.DEEP_DRAWDOWN).account())
        assertEquals(31.0, a.summary.drawdownNowPct, 0.0)
        assertEquals(32.5, a.summary.drawdownWorstPct, 0.0)
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

    @Test fun staleScenarioIsBehindOnEveryScreenAndOthersAreNot() = runBlocking {
        val l = loader(Scenario.STALE)
        assertEquals("Updated 4 days ago", Freshness.line(data(l.today())))
        assertEquals("Updated 4 days ago", Freshness.line(data(l.account())))
        assertEquals("Updated 4 days ago", Freshness.line(data(l.positions())))
        assertEquals("Updated 4 days ago", Freshness.line(data(l.trades())))
        for (s in Scenario.entries.filter { it != Scenario.STALE && it != Scenario.ERROR }) {
            assertNull("$s", Freshness.line(data(loader(s).account())))
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
        try {
            repo(Scenario.ERROR).getToday()
            fail("the repository throws in the ERROR scenario")
        } catch (e: ApiException) {
            assertEquals(ErrorCode.NOT_READY, e.code)
        }
    }

    @Test fun switchingScenarioChangesWhatTheRepositoryReturns() = runBlocking {
        val repo = repo(Scenario.EMPTY)
        val l = ScreenLoader(repo)
        assertTrue(l.trades() is ScreenState.Empty)
        repo.select(Scenario.TRADES)
        assertTrue(l.trades() is ScreenState.Content)
        repo.select(Scenario.ERROR)
        assertTrue(l.trades() is ScreenState.Error)
        assertTrue(repo.isSample)
    }
}
