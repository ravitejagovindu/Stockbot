package com.stockbot.paper

import com.stockbot.paper.format.RupeeFormat
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate

/** Money comes in as paise: 1 rupee = 100 paise. */
class RupeeFormatTest {
    private val minus = "−"
    private val rs = "₹"

    private fun rupees(r: Long) = r * 100

    @Test fun smallValuesHaveNoSeparator() {
        assertEquals("${rs}0", RupeeFormat.format(0))
        assertEquals("${rs}7", RupeeFormat.format(rupees(7)))
        assertEquals("${rs}999", RupeeFormat.format(rupees(999)))
    }

    @Test fun indianGroupingUsesLastThreeThenPairs() {
        assertEquals("${rs}1,000", RupeeFormat.format(rupees(1_000)))
        assertEquals("${rs}12,345", RupeeFormat.format(rupees(12_345)))
        assertEquals("${rs}1,00,000", RupeeFormat.format(rupees(100_000)))
        assertEquals("${rs}2,14,300", RupeeFormat.format(21_430_000))
        assertEquals("${rs}2,00,000", RupeeFormat.format(20_000_000))
        assertEquals("${rs}1,23,45,678", RupeeFormat.format(rupees(12_345_678)))
    }

    @Test fun largeValues() {
        assertEquals("${rs}10,00,00,000", RupeeFormat.format(rupees(100_000_000)))
        assertEquals("${rs}10,00,00,00,000", RupeeFormat.format(rupees(10_000_000_000)))
        assertEquals("${rs}99,99,99,99,999", RupeeFormat.format(rupees(99_99_99_99_999)))
        // Near the top of the 64-bit range: still exact, no overflow, no rounding through a double.
        assertEquals("${rs}92,23,37,20,36,85,47,758.07", RupeeFormat.format(Long.MAX_VALUE))
        assertEquals("${minus}${rs}92,23,37,20,36,85,47,758.08", RupeeFormat.format(Long.MIN_VALUE))
    }

    @Test fun negativesUseARealMinusBeforeTheSymbol() {
        assertEquals("${minus}${rs}1,250", RupeeFormat.format(-rupees(1_250)))
        assertEquals("${minus}${rs}2,14,300", RupeeFormat.format(-21_430_000))
        assertEquals('−', RupeeFormat.format(-500)[0])
    }

    @Test fun signedAddsPlusOnlyForGains() {
        assertEquals("+${rs}1,250", RupeeFormat.format(rupees(1_250), signed = true))
        assertEquals("${minus}${rs}1,250", RupeeFormat.format(-rupees(1_250), signed = true))
        assertEquals("${rs}0", RupeeFormat.format(0, signed = true))
    }

    @Test fun paiseOnlyWhenNeeded() {
        assertEquals("${rs}1,234.50", RupeeFormat.format(123_450))
        assertEquals("${rs}1,642.30", RupeeFormat.format(164_230))
        assertEquals("${rs}3,985", RupeeFormat.format(398_500))
        assertEquals("${rs}0.05", RupeeFormat.format(5))
        assertEquals("${rs}0.50", RupeeFormat.format(50))
        assertEquals("${minus}${rs}12.75", RupeeFormat.format(-1_275))
        assertEquals("${rs}1,999.80", RupeeFormat.format(199_980))
    }

    @Test fun percentAndR() {
        assertEquals("+1.3%", RupeeFormat.percent(1.25))
        assertEquals("${minus}0.4%", RupeeFormat.percent(-0.4))
        assertEquals("0.0%", RupeeFormat.percent(-0.04))
        assertEquals("31.0%", RupeeFormat.percent(31.0, signed = false))
        assertEquals("42%", RupeeFormat.wholePercent(41.67))
        assertEquals("+2.0R", RupeeFormat.r(1.95))
        assertEquals("${minus}1.0R", RupeeFormat.r(-1.0))
        assertEquals("1", RupeeFormat.wholeOrOneDecimal(1.0))
        assertEquals("0.5", RupeeFormat.wholeOrOneDecimal(0.5))
    }

    @Test fun datesAreShort() {
        assertEquals("3 Nov", RupeeFormat.date(LocalDate.of(2026, 11, 3)))
        assertEquals("3 Nov 2026", RupeeFormat.dateYear(LocalDate.of(2026, 11, 3)))
    }
}
