package com.stockbot.paper.format

import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Rupee and number formatting. Money comes in as integer paise. Indian digit grouping (2,14,300), a real minus sign, no paise unless needed. */
object RupeeFormat {
    const val MINUS = "−"
    private const val RUPEE = "₹"

    /** "₹2,14,300" for 21430000, "−₹1,250" for -125000, "₹1,234.50" for 123450. With [signed], gains get a leading "+". */
    fun format(paise: Long, signed: Boolean = false): String {
        val negative = paise < 0
        val abs = BigDecimal.valueOf(paise, 2).abs()
        val whole = abs.setScale(0, RoundingMode.DOWN).toBigInteger().toString()
        val p = abs.remainder(BigDecimal.ONE).movePointRight(2).toInt()
        val body = RUPEE + group(whole) + if (p != 0) String.format(Locale.US, ".%02d", p) else ""
        return when {
            negative -> MINUS + body
            signed && paise > 0 -> "+$body"
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

    private val DATE_TIME = DateTimeFormatter.ofPattern("d MMM, HH:mm", Locale.ENGLISH)

    /** "24 Nov, 19:48" from an ISO 8601 timestamp with an offset (the offset of the timestamp is kept); the text itself when it cannot be read. */
    fun dateTime(iso: String): String = try {
        java.time.OffsetDateTime.parse(iso).format(DATE_TIME)
    } catch (e: Exception) {
        iso
    }

    fun date(d: LocalDate): String = d.format(DATE)
    fun dateYear(d: LocalDate): String = d.format(DATE_YEAR)
}
