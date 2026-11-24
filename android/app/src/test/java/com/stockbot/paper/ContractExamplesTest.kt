package com.stockbot.paper

import com.stockbot.paper.data.AccountSnapshot
import com.stockbot.paper.data.ApiException
import com.stockbot.paper.data.BlockReason
import com.stockbot.paper.data.Contract
import com.stockbot.paper.data.Envelope
import com.stockbot.paper.data.ErrorCode
import com.stockbot.paper.data.PositionsState
import com.stockbot.paper.data.Scenario
import com.stockbot.paper.data.TodayState
import com.stockbot.paper.data.TradesState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.time.OffsetDateTime
import java.time.ZoneOffset
import kotlin.math.abs

/** Every example file of the contract parses into the models, and the figures inside each scenario reconcile. */
class ContractExamplesTest {
    private val start = 20_000_000L
    private val scenarios = Scenario.entries.filter { it != Scenario.ERROR }

    private fun text(name: String) = TestExamples.source.read(name)
    private fun today(s: Scenario) = Contract.today(text("today_${s.fileSuffix}.json"))
    private fun account(s: Scenario) = Contract.account(text("account_${s.fileSuffix}.json"))
    private fun positions(s: Scenario) = Contract.positions(text("positions_${s.fileSuffix}.json"))
    private fun trades(s: Scenario) = Contract.trades(text("trades_${s.fileSuffix}.json"))

    private fun assertEnvelope(label: String, e: Envelope) {
        assertEquals("$label apiVersion", "1", e.apiVersion)
        assertTrue("$label dataAsOf <= expectedAsOf", !e.dataAsOf.isAfter(e.expectedAsOf))
        val at = OffsetDateTime.parse(e.generatedAt)
        assertEquals("$label generatedAt offset", ZoneOffset.ofHoursMinutes(5, 30), at.offset)
    }

    @Test fun everyExampleFileIsReadByTheMatchingParser() {
        val names = TestExamples.names()
        assertTrue("expected at least 28 example files, found ${names.size}", names.size >= 28)
        for (n in names) {
            val body = text(n)
            when {
                n.startsWith("today_") -> assertEnvelope(n, Contract.today(body))
                n.startsWith("account_") -> assertEnvelope(n, Contract.account(body))
                n.startsWith("positions_") -> assertEnvelope(n, Contract.positions(body))
                n.startsWith("trades_") -> assertEnvelope(n, Contract.trades(body))
                n.startsWith("health_") -> {
                    val h = Contract.health(body)
                    assertEnvelope(n, h)
                    assertEquals(h.generatedAt, h.serverTime)
                    assertEquals(h.latestSealedDate, h.dataAsOf)
                }
                n.startsWith("error_") -> {
                    val ex = Contract.error(body)
                    assertTrue(n, n.contains(ex.code.name.lowercase()))
                    assertTrue(ex.message!!.isNotBlank())
                    assertFalse(ex.message!!.contains("!") || ex.message!!.lowercase().contains("please"))
                }
                else -> fail("unexpected example file $n")
            }
        }
    }

    @Test fun everyScenarioHasAllFourBodiesAndErrorsAreThrown() {
        for (s in scenarios) {
            today(s); account(s); positions(s); trades(s)
        }
        for (code in listOf("unauthorized", "not_ready", "server_error")) {
            val ex = runCatching { Contract.today(text("error_$code.json")) }.exceptionOrNull()
            assertTrue("error_$code is thrown, not parsed", ex is ApiException)
            assertEquals(code.uppercase(), (ex as ApiException).code.name)
        }
    }

    @Test fun equityIsCashPlusPositionsAndAccountAndPositionsAgree() {
        for (s in scenarios) {
            val a = account(s).summary
            val p = positions(s)
            val marked = p.positions.sumOf { it.shares * it.lastClosePaise }
            assertEquals("$s equity = cash + positions", a.equityPaise, a.cashPaise + marked)
            assertEquals("$s cash on both screens", a.cashPaise, p.cashPaise)
            assertEquals("$s start", start, a.startingCapitalPaise)
            p.positions.forEach {
                assertEquals("$s ${it.symbol} unrealised", it.shares * (it.lastClosePaise - it.entryPricePaise), it.unrealisedPnlPaise)
                assertTrue("$s ${it.symbol} stop below entry", it.stopPaise < it.entryPricePaise)
            }
        }
    }

    @Test fun accountReturnsAreFromEquityAndNifty() {
        for (s in scenarios) {
            val acc = account(s)
            val sum = acc.summary
            assertEquals("$s returnPct", (sum.equityPaise.toDouble() / sum.startingCapitalPaise - 1) * 100, sum.returnPct, 0.006)
            assertEquals("$s niftyReturnPct", (acc.curve.last().niftyPaise.toDouble() / sum.startingCapitalPaise - 1) * 100, sum.niftyReturnPct, 0.006)
        }
    }

    @Test fun curveStartsAtCapitalEndsAtEquityAndSharesDates() {
        for (s in scenarios) {
            val acc = account(s)
            val c = acc.curve
            assertTrue("$s has points", c.size >= 2)
            assertEquals("$s first date", acc.summary.startDate, c.first().date)
            assertEquals("$s last date", acc.dataAsOf, c.last().date)
            assertEquals("$s account starts at capital", start, c.first().accountPaise)
            assertEquals("$s nifty starts at capital (rebased)", start, c.first().niftyPaise)
            assertEquals("$s account ends at equity", acc.summary.equityPaise, c.last().accountPaise)
            assertTrue("$s dates ascend, one per day", c.zipWithNext().all { (x, y) -> x.date < y.date })
        }
    }

    @Test fun drawdownsMatchTheCurve() {
        for (s in scenarios) {
            val acc = account(s)
            var peak = 0L
            var worst = 0.0
            for (p in acc.curve) {
                peak = maxOf(peak, p.accountPaise)
                worst = maxOf(worst, (peak - p.accountPaise).toDouble() / peak * 100)
            }
            val now = (peak - acc.curve.last().accountPaise).toDouble() / peak * 100
            assertEquals("$s now", now, acc.summary.drawdownNowPct, 0.006)
            assertEquals("$s worst", maxOf(worst, now), acc.summary.drawdownWorstPct, 0.006)
            assertTrue("$s drawdowns are positive numbers", acc.summary.drawdownNowPct >= 0 && acc.summary.drawdownWorstPct >= acc.summary.drawdownNowPct)
        }
    }

    @Test fun tradeFootersAreServerFiguresThatMatchTheList() {
        for (s in scenarios) {
            val t = trades(s)
            val st = t.stats
            assertEquals("$s count", t.trades.size, st.tradeCount)
            assertEquals("$s wins", t.trades.count { it.netPnlPaise > 0 }, st.wins)
            assertEquals("$s losses", t.trades.count { it.netPnlPaise < 0 }, st.losses)
            if (t.trades.isEmpty()) {
                assertNull(st.winRatePct); assertNull(st.profitFactor)
            } else {
                assertEquals("$s win rate", st.wins * 100.0 / st.tradeCount, st.winRatePct!!, 0.006)
                val gw = t.trades.filter { it.netPnlPaise > 0 }.sumOf { it.netPnlPaise }.toDouble()
                val gl = -t.trades.filter { it.netPnlPaise < 0 }.sumOf { it.netPnlPaise }.toDouble()
                assertEquals("$s profit factor", gw / gl, st.profitFactor!!, 0.006)
            }
            assertEquals("$s closed trades on the Account screen", st.tradeCount, account(s).summary.closedTrades)
            assertTrue("$s newest exit first", t.trades.zipWithNext().all { (x, y) -> !x.exitDate.isBefore(y.exitDate) })
            t.trades.forEach { assertTrue("$s ${it.symbol} enters before it exits", it.entryDate < it.exitDate) }
        }
    }

    @Test fun withoutOpenPositionsEquityIsStartPlusRealisedPnl() {
        for (s in scenarios) {
            val p = positions(s)
            if (p.positions.isEmpty()) {
                val acc = account(s)
                assertEquals("$s equity", start + trades(s).trades.sumOf { it.netPnlPaise }, acc.summary.equityPaise)
            }
        }
    }

    @Test fun emptyMatchesTheRealStateToday() {
        val a = account(Scenario.EMPTY)
        assertEquals(20_000_000L, a.summary.startingCapitalPaise)
        assertEquals(20_000_000L, a.summary.equityPaise)
        assertEquals(20_000_000L, a.summary.cashPaise)
        assertEquals(0, a.summary.closedTrades)
        assertEquals(setOf(20_000_000L), a.curve.map { it.accountPaise }.toSet())
        val t = today(Scenario.EMPTY)
        assertFalse(t.isSignalDay)
        assertTrue(t.tickets.isEmpty() && t.blocked.isEmpty() && t.pendingFills.isEmpty())
        assertTrue(positions(Scenario.EMPTY).positions.isEmpty())
        assertTrue(trades(Scenario.EMPTY).trades.isEmpty())
        assertEquals(30, a.marks.closedTradesTarget)
        assertEquals(35.0, a.marks.drawdownReviewPct, 0.0)
        assertEquals("not demonstrated", a.marks.verdict)
    }

    @Test fun signalDayTicketsAreSizedForOnePercentRisk() {
        val t = today(Scenario.SIGNAL_DAY)
        assertTrue(t.isSignalDay)
        assertEquals(3, t.tickets.size)
        assertEquals(12, t.blocked.size)
        assertTrue(t.blocked.all { it.reason == BlockReason.SECTOR_CAP })
        assertEquals(1.0, t.riskPerTradePct, 0.0)
        t.tickets.forEach {
            assertEquals("${it.symbol} risk = shares x (entry - stop)", it.shares * (it.entryReferencePaise - it.stopPaise), it.riskPaise)
            // 1% of Rs 2,00,000 is 2,00,000 paise; whole shares mean the risk is a little under it.
            assertTrue("${it.symbol} ${it.riskPaise}", it.riskPaise in 180_000..200_000)
        }
    }

    @Test fun tradesScenarioHasFiveWinsAndProfitFactorOnePointFour() {
        val s = trades(Scenario.TRADES).stats
        assertEquals(12, s.tradeCount); assertEquals(5, s.wins); assertEquals(7, s.losses)
        assertEquals(1.4, s.profitFactor!!, 0.0001)
    }

    @Test fun deepDrawdownHasItsOwnConsistentTrades() {
        val acc = account(Scenario.DEEP_DRAWDOWN)
        assertEquals(31.0, acc.summary.drawdownNowPct, 0.0)
        assertEquals(32.5, acc.summary.drawdownWorstPct, 0.0)
        assertEquals(26_000_000L, acc.curve.maxOf { it.accountPaise })
        assertEquals(17_940_000L, acc.summary.equityPaise)
        val t = trades(Scenario.DEEP_DRAWDOWN)
        assertEquals(25, t.trades.size)
        assertEquals(acc.summary.equityPaise - start, t.trades.sumOf { it.netPnlPaise })
        // The curve is the running total of realised P&L by exit date.
        for (p in acc.curve) {
            assertEquals(start + t.trades.filter { !it.exitDate.isAfter(p.date) }.sumOf { it.netPnlPaise }, p.accountPaise)
        }
    }

    @Test fun staleExampleIsTwoTradingDaysBehind() {
        for (r in listOf<Envelope>(today(Scenario.STALE), account(Scenario.STALE), positions(Scenario.STALE), trades(Scenario.STALE))) {
            assertEquals(4, com.stockbot.paper.data.Freshness.daysBehind(r))
            assertEquals("Updated 4 days ago", com.stockbot.paper.data.Freshness.line(r))
        }
    }

    @Test fun healthAndErrorsFollowTheContract() {
        assertEquals("ok", Contract.health(text("health_ok.json")).status)
        assertEquals(ErrorCode.UNAUTHORIZED, Contract.error(text("error_unauthorized.json")).code)
        assertEquals(ErrorCode.NOT_READY, Contract.error(text("error_not_ready.json")).code)
        assertEquals(ErrorCode.SERVER_ERROR, Contract.error(text("error_server_error.json")).code)
    }

    @Test fun pendingFillsAndNullableFieldsParse() {
        val p = today(Scenario.POSITIONS).pendingFills
        assertEquals(1, p.size)
        assertEquals("MARUTI", p[0].symbol)
        assertNotNull(Contract.today(text("today_signal_day.json")).tickets.first().sector)
        assertTrue(abs(1.0) > 0)
    }
}
