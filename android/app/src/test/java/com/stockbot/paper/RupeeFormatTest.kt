package com.stockbot.paper

import com.stockbot.paper.format.RupeeFormat
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate

class RupeeFormatTest {
    private val minus = "−"
    private val rs = "₹"

    @Test fun smallValuesHaveNoSeparator() {
        assertEquals("${rs}0", RupeeFormat.format(0.0))
        assertEquals("${rs}7", RupeeFormat.format(7.0))
        assertEquals("${rs}999", RupeeFormat.format(999.0))
    }

    @Test fun indianGroupingUsesLastThreeThenPairs() {
        assertEquals("${rs}1,000", RupeeFormat.format(1_000.0))
        assertEquals("${rs}12,345", RupeeFormat.format(12_345.0))
        assertEquals("${rs}1,00,000", RupeeFormat.format(100_000.0))
        assertEquals("${rs}2,14,300", RupeeFormat.format(214_300.0))
        assertEquals("${rs}2,00,000", RupeeFormat.format(200_000.0))
        assertEquals("${rs}1,23,45,678", RupeeFormat.format(12_345_678.0))
    }

    @Test fun largeValues() {
        assertEquals("${rs}10,00,00,000", RupeeFormat.format(100_000_000.0))
        assertEquals("${rs}10,00,00,00,000", RupeeFormat.format(10_000_000_000.0))
        assertEquals("${rs}99,99,99,99,999", RupeeFormat.format(99_99_99_99_999.0))
    }

    @Test fun negativesUseARealMinusBeforeTheSymbol() {
        assertEquals("${minus}${rs}1,250", RupeeFormat.format(-1_250.0))
        assertEquals("${minus}${rs}2,14,300", RupeeFormat.format(-214_300.0))
        assertEquals('−', RupeeFormat.format(-5.0)[0])
    }

    @Test fun signedAddsPlusOnlyForGains() {
        assertEquals("+${rs}1,250", RupeeFormat.format(1_250.0, signed = true))
        assertEquals("${minus}${rs}1,250", RupeeFormat.format(-1_250.0, signed = true))
        assertEquals("${rs}0", RupeeFormat.format(0.0, signed = true))
    }

    @Test fun paiseOnlyWhenNeeded() {
        assertEquals("${rs}1,234.50", RupeeFormat.format(1_234.5))
        assertEquals("${rs}1,642.30", RupeeFormat.format(1_642.30))
        assertEquals("${rs}3,985", RupeeFormat.format(3_985.00))
        assertEquals("${rs}0.05", RupeeFormat.format(0.05))
        assertEquals("${minus}${rs}12.75", RupeeFormat.format(-12.75))
    }

    @Test fun valuesThatRoundToZeroHaveNoSign() {
        assertEquals("${rs}0", RupeeFormat.format(-0.004))
        assertEquals("${rs}0", RupeeFormat.format(0.004, signed = true))
    }

    @Test fun roundingIsHalfUpAtTwoDecimals() {
        assertEquals("${rs}10.01", RupeeFormat.format(10.005))
        assertEquals("${rs}1,000", RupeeFormat.format(999.999))
    }

    @Test fun priceKeepsTwoDecimals() {
        assertEquals("1,642.30", RupeeFormat.price(1_642.3))
        assertEquals("12,480.00", RupeeFormat.price(12_480.0))
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
