package com.stockbot.paper.format

import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Rupee and number formatting. Indian digit grouping (2,14,300), a real minus sign, no paise unless needed. */
object RupeeFormat {
    const val MINUS = "−"
    private const val RUPEE = "₹"

    private fun twoDecimals(value: Double): BigDecimal = BigDecimal.valueOf(value).setScale(2, RoundingMode.HALF_UP)

    private fun wholeDigits(abs: BigDecimal): String = abs.setScale(0, RoundingMode.DOWN).toBigInteger().toString()

    private fun paise(abs: BigDecimal): Int = abs.remainder(BigDecimal.ONE).movePointRight(2).toInt()

    /** "₹2,14,300", "−₹1,250", "₹1,234.50". With [signed], gains get a leading "+". */
    fun format(value: Double, signed: Boolean = false): String {
        val rounded = twoDecimals(value)
        val abs = rounded.abs()
        val p = paise(abs)
        val body = RUPEE + group(wholeDigits(abs)) + if (p != 0) String.format(Locale.US, ".%02d", p) else ""
        return when {
            rounded.signum() < 0 -> MINUS + body
            signed && rounded.signum() > 0 -> "+$body"
            else -> body
        }
    }

    /** Indian grouping of a non-negative digit string: last three digits, then pairs. */
    fun group(digits: String): String {
        if (digits.length <= 3) return digits
        val head = digits.substring(0, digits.length - 3)
        val tail = digits.substring(digits.length - 3)
        val pairs = head.reversed().chunked(2).joinToString(",").reversed()
        return "$pairs,$tail"
    }

    /** A price with two decimals and Indian grouping, no symbol: "1,642.30". */
    fun price(value: Double): String {
        val rounded = twoDecimals(value)
        val abs = rounded.abs()
        val body = group(wholeDigits(abs)) + String.format(Locale.US, ".%02d", paise(abs))
        return if (rounded.signum() < 0) MINUS + body else body
    }

    /** "+1.2%", "−0.4%", "0.0%". One decimal. */
    fun percent(value: Double, signed: Boolean = true): String {
        val rounded = BigDecimal.valueOf(value).setScale(1, RoundingMode.HALF_UP)
        val body = String.format(Locale.US, "%.1f%%", rounded.abs())
        return when {
            rounded.signum() < 0 -> MINUS + body
            signed && rounded.signum() > 0 -> "+$body"
            else -> body
        }
    }

    /** Whole percent for a rate: "42%". */
    fun wholePercent(value: Double): String = String.format(Locale.US, "%d%%", Math.round(value))

    /** "1" for 1.0, "0.5" for 0.5. */
    fun wholeOrOneDecimal(value: Double): String =
        if (value == Math.rint(value)) String.format(Locale.US, "%d", value.toLong()) else String.format(Locale.US, "%.1f", value)

    /** "+2.1R", "−1.0R". */
    fun r(value: Double): String {
        val rounded = BigDecimal.valueOf(value).setScale(1, RoundingMode.HALF_UP)
        val body = String.format(Locale.US, "%.1fR", rounded.abs())
        return when {
            rounded.signum() < 0 -> MINUS + body
            rounded.signum() > 0 -> "+$body"
            else -> body
        }
    }

    private val DATE = DateTimeFormatter.ofPattern("d MMM", Locale.ENGLISH)
    private val DATE_YEAR = DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH)

    fun date(d: LocalDate): String = d.format(DATE)
    fun dateYear(d: LocalDate): String = d.format(DATE_YEAR)
}
