package com.stockbot.paper

import com.stockbot.paper.data.ApiException
import com.stockbot.paper.data.BlockReason
import com.stockbot.paper.data.Contract
import com.stockbot.paper.data.ErrorCode
import com.stockbot.paper.data.ExitReason
import com.stockbot.paper.data.Freshness
import com.stockbot.paper.data.Side
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.time.LocalDate

class EnumAndFreshnessTest {
    private val head = """"apiVersion":"1","dataAsOf":"2026-12-01","expectedAsOf":"2026-12-01","generatedAt":"2026-12-01T19:48:30+05:30""""

    @Test fun unknownExitReasonBecomesOther() {
        val body = """{$head,"trades":[
            {"symbol":"AAA","entryDate":"2026-11-02","exitDate":"2026-11-20","exitReason":"SOMETHING_NEW","netPnlPaise":-12345,"netR":-0.5},
            {"symbol":"BBB","entryDate":"2026-11-02","exitDate":"2026-11-19","exitReason":"stop_hit","netPnlPaise":100,"netR":0.1},
            {"symbol":"CCC","entryDate":"2026-11-02","exitDate":"2026-11-18","exitReason":"GAP_THROUGH_STOP","netPnlPaise":-300,"netR":-1.5}
          ],"stats":{"tradeCount":3,"wins":1,"losses":2,"winRatePct":33.33,"profitFactor":0.0}}"""
        val t = Contract.trades(body).trades
        assertEquals(ExitReason.OTHER, t[0].exitReason)
        assertEquals("names are exact, so a different case is unknown", ExitReason.OTHER, t[1].exitReason)
        assertEquals(ExitReason.GAP_THROUGH_STOP, t[2].exitReason)
    }

    @Test fun corporateActionFieldsDefaultToFalseAndZeroWhenAbsent() {
        val old = """{$head,"trades":[{"symbol":"AAA","entryDate":"2026-11-02","exitDate":"2026-11-20","exitReason":"STOP_HIT","netPnlPaise":-100,"netR":-0.5}],
            "stats":{"tradeCount":1,"wins":0,"losses":1,"winRatePct":0.0,"profitFactor":0.0}}"""
        val t = Contract.trades(old)
        assertEquals(false, t.trades[0].corporateActionFlag)
        assertEquals(0, t.stats.excludedFromStats)
        val pos = Contract.positions("""{$head,"cashPaise":1,"positions":[{"symbol":"AAA","shares":1,"entryDate":"2026-11-02","entryPricePaise":100,"stopPaise":90,"lastClosePaise":110,"unrealisedPnlPaise":10}]}""")
        assertEquals(false, pos.positions[0].corporateActionFlag)
    }

    @Test fun unknownBlockReasonAndSideBecomeOther() {
        val body = """{$head,"isSignalDay":true,"riskPerTradePct":1.0,"tickets":[],
            "blocked":[{"symbol":"AAA","sector":null,"reason":"MARKET_SWITCH"},{"symbol":"BBB","sector":"IT","reason":"CASH"},
                       {"symbol":"CCC","sector":"IT","reason":"RISK_CAP"},{"symbol":"DDD","sector":"IT","reason":"SECTOR_CAP"},{"symbol":"EEE","sector":"IT","reason":""}],
            "pendingFills":[{"symbol":"AAA","side":"SHORT","shares":1,"note":"x"},{"symbol":"BBB","side":"BUY","shares":1,"note":"x"},{"symbol":"CCC","side":"SELL","shares":1,"note":"x"}],
            "nextSignalRule":"first trading day of next month"}"""
        val t = Contract.today(body)
        assertEquals(
            listOf(BlockReason.OTHER, BlockReason.CASH, BlockReason.RISK_CAP, BlockReason.SECTOR_CAP, BlockReason.OTHER),
            t.blocked.map { it.reason },
        )
        assertNull(t.blocked[0].sector)
        assertEquals(listOf(Side.OTHER, Side.BUY, Side.SELL), t.pendingFills.map { it.side })
    }

    @Test fun unknownErrorCodeBecomesServerErrorAndUnknownKeysAreIgnored() {
        val ex = Contract.error("""{"apiVersion":"1","extra":1,"error":{"code":"TEAPOT","message":"Short.","more":true}}""")
        assertEquals(ErrorCode.SERVER_ERROR, ex.code)
        val h = Contract.health("""{"apiVersion":"1","status":"ok","serverTime":"2026-12-01T19:48:31+05:30","latestSealedDate":null,"dataAsOf":"2026-12-01","expectedAsOf":"2026-12-01","generatedAt":"2026-12-01T19:48:31+05:30","newField":[1,2]}""")
        assertNull(h.latestSealedDate)
    }

    @Test fun anotherApiVersionIsRefusedCalmly() {
        try {
            Contract.trades("""{"apiVersion":"2","dataAsOf":"2026-12-01","expectedAsOf":"2026-12-01","generatedAt":"2026-12-01T19:48:30+05:30","trades":[],"stats":{"tradeCount":0,"wins":0,"losses":0,"winRatePct":null,"profitFactor":null}}""")
            fail("version 2 must not be read as version 1")
        } catch (e: ApiException) {
            assertTrue(e.message!!.contains("2"))
        }
    }

    @Test fun garbageBecomesACalmError() {
        for (bad in listOf("", "not json", "[]", """{"apiVersion":"1"}""")) {
            try {
                Contract.today(bad)
                fail("'$bad' must not parse")
            } catch (e: ApiException) {
                assertEquals(ErrorCode.SERVER_ERROR, e.code)
            }
        }
    }

    // ------------------------------------------------------------------ the stale rule: only when dataAsOf is before expectedAsOf

    private fun d(s: String) = LocalDate.parse(s)

    @Test fun fridayDataOnMondayMorningIsNotStaleWhenFridayIsExpected() {
        // Monday 2026-11-23 morning: the last trading day on which data is expected is still Friday 2026-11-20.
        assertNull(Freshness.daysBehind(d("2026-11-20"), d("2026-11-20")))
    }

    @Test fun twoTradingDaysBehindIsStale() {
        // Data of Friday 2026-11-20, but Tuesday 2026-11-24 is expected: Monday and Tuesday are missing.
        assertEquals(4, Freshness.daysBehind(d("2026-11-20"), d("2026-11-24")))
    }

    @Test fun oneTradingDayBehindIsStaleToo() {
        assertEquals(1, Freshness.daysBehind(d("2026-11-23"), d("2026-11-24")))
    }

    @Test fun currentDataAndDataAheadOfExpectationAreNotStale() {
        assertNull(Freshness.daysBehind(d("2026-11-24"), d("2026-11-24")))
        assertNull(Freshness.daysBehind(d("2026-11-25"), d("2026-11-24")))
    }

    @Test fun lineWording() {
        val e = Contract.today("""{"apiVersion":"1","dataAsOf":"2026-11-23","expectedAsOf":"2026-11-24","generatedAt":"2026-11-24T19:48:30+05:30","isSignalDay":false,"riskPerTradePct":1.0,"tickets":[],"blocked":[],"pendingFills":[],"nextSignalRule":"x"}""")
        assertEquals("Updated 1 day ago", Freshness.line(e))
    }
}
