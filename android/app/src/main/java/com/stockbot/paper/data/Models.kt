package com.stockbot.paper.data

import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import java.time.LocalDate

/*
 * Response models of the StockBot Paper API, version 1 (docs/android/contract/CONTRACT.md is the frozen contract).
 * Money is integer PAISE (Long). Percentages are decimal numbers in percent units (1.5 means 1.5%); drawdowns are positive.
 * Dates are yyyy-MM-dd. Property names are the JSON keys. List-valued fields are never null.
 */

const val API_VERSION = "1"

/** Fields every response carries. */
interface Envelope {
    val apiVersion: String

    /** The date of the data. */
    val dataAsOf: LocalDate

    /** The last trading day on which data is expected. */
    val expectedAsOf: LocalDate

    /** When the server built the response, ISO 8601 with the +05:30 offset. */
    val generatedAt: String
}

// ---------------------------------------------------------------------------------------------------------------- serialisers

object LocalDateSerializer : KSerializer<LocalDate> {
    override val descriptor = PrimitiveSerialDescriptor("LocalDate", PrimitiveKind.STRING)
    override fun deserialize(decoder: Decoder): LocalDate = LocalDate.parse(decoder.decodeString())
    override fun serialize(encoder: Encoder, value: LocalDate) = encoder.encodeString(value.toString())
}

/** Reads an enum by name; a value this app version does not know becomes [fallback] and never fails. */
open class SafeEnumSerializer<T : Enum<T>>(private val values: Array<T>, private val fallback: T) : KSerializer<T> {
    override val descriptor = PrimitiveSerialDescriptor("SafeEnum", PrimitiveKind.STRING)
    override fun deserialize(decoder: Decoder): T {
        val s = decoder.decodeString()
        return values.firstOrNull { it.name == s } ?: fallback
    }

    override fun serialize(encoder: Encoder, value: T) = encoder.encodeString(value.name)
}

object ExitReasonSerializer : SafeEnumSerializer<ExitReason>(ExitReason.entries.toTypedArray(), ExitReason.OTHER)
object BlockReasonSerializer : SafeEnumSerializer<BlockReason>(BlockReason.entries.toTypedArray(), BlockReason.OTHER)
object SideSerializer : SafeEnumSerializer<Side>(Side.entries.toTypedArray(), Side.OTHER)
object ErrorCodeSerializer : SafeEnumSerializer<ErrorCode>(ErrorCode.entries.toTypedArray(), ErrorCode.SERVER_ERROR)

// ---------------------------------------------------------------------------------------------------------------- enums

@Serializable(with = ExitReasonSerializer::class)
enum class ExitReason(val label: String) {
    STOP_HIT("Stop hit"),
    GAP_THROUGH_STOP("Gap through stop"),
    OTHER("Other"),
}

@Serializable(with = BlockReasonSerializer::class)
enum class BlockReason { SECTOR_CAP, CASH, RISK_CAP, OTHER }

/** BUY and SELL are the contract's values; OTHER only catches a value from a newer server. */
@Serializable(with = SideSerializer::class)
enum class Side { BUY, SELL, OTHER }

@Serializable(with = ErrorCodeSerializer::class)
enum class ErrorCode { UNAUTHORIZED, NOT_READY, SERVER_ERROR }

// ---------------------------------------------------------------------------------------------------------------- errors

@Serializable
data class ErrorBody(val code: ErrorCode, val message: String)

@Serializable
data class ErrorResponse(val apiVersion: String, val error: ErrorBody)

/** Thrown for a non-200 response or an unusable body; the UI shows a calm one-line error. */
class ApiException(val code: ErrorCode, message: String) : RuntimeException(message)

// ---------------------------------------------------------------------------------------------------------------- /v1/health

@Serializable
data class HealthResponse(
    override val apiVersion: String,
    val status: String,
    val serverTime: String,
    /** Latest sealed data date; null before any data is sealed. */
    @Serializable(with = LocalDateSerializer::class) val latestSealedDate: LocalDate?,
    @Serializable(with = LocalDateSerializer::class) override val dataAsOf: LocalDate,
    @Serializable(with = LocalDateSerializer::class) override val expectedAsOf: LocalDate,
    override val generatedAt: String,
) : Envelope

// ---------------------------------------------------------------------------------------------------------------- /v1/today

@Serializable
data class Ticket(
    val symbol: String,
    /** Null when the sector is not known. */
    val sector: String?,
    val shares: Int,
    /** Last close the suggestion is based on; the fill is at the next open. Paise per share. */
    val entryReferencePaise: Long,
    val stopPaise: Long,
    /** Paise lost if the stop is hit, before costs. */
    val riskPaise: Long,
)

@Serializable
data class BlockedItem(
    val symbol: String,
    val sector: String?,
    val reason: BlockReason,
)

/** An order that will fill at the next open. */
@Serializable
data class PendingFill(
    val symbol: String,
    val side: Side,
    val shares: Int,
    /** Short reason in plain words. */
    val note: String,
)

@Serializable
data class TodayState(
    override val apiVersion: String,
    @Serializable(with = LocalDateSerializer::class) override val dataAsOf: LocalDate,
    @Serializable(with = LocalDateSerializer::class) override val expectedAsOf: LocalDate,
    override val generatedAt: String,
    val isSignalDay: Boolean,
    /** Risk per suggestion as a percent of equity (1.0 means 1%). */
    val riskPerTradePct: Double,
    val tickets: List<Ticket>,
    val blocked: List<BlockedItem>,
    val pendingFills: List<PendingFill>,
    /** Plain-language rule for the next signal day. */
    val nextSignalRule: String,
) : Envelope

// ---------------------------------------------------------------------------------------------------------------- /v1/account

@Serializable
data class AccountSummary(
    @Serializable(with = LocalDateSerializer::class) val startDate: LocalDate,
    val startingCapitalPaise: Long,
    val equityPaise: Long,
    val cashPaise: Long,
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

/** One trading day. Nifty is already rebased to the starting capital, in paise, so both lines share one axis. */
@Serializable
data class EquityPoint(
    @Serializable(with = LocalDateSerializer::class) val date: LocalDate,
    val accountPaise: Long,
    val niftyPaise: Long,
)

@Serializable
data class ReviewMarks(
    /** Drawdown (percent below peak) at which the account is reviewed. */
    val drawdownReviewPct: Double,
    /** Closed trades needed before the first verdict can be given. */
    val closedTradesTarget: Int,
    /** The registered verdict, shown as it is: "not demonstrated". */
    val verdict: String,
)

@Serializable
data class AccountSnapshot(
    override val apiVersion: String,
    @Serializable(with = LocalDateSerializer::class) override val dataAsOf: LocalDate,
    @Serializable(with = LocalDateSerializer::class) override val expectedAsOf: LocalDate,
    override val generatedAt: String,
    val summary: AccountSummary,
    /** One point per trading day, oldest first, same dates for both lines. */
    val curve: List<EquityPoint>,
    val marks: ReviewMarks,
) : Envelope

// ---------------------------------------------------------------------------------------------------------------- /v1/positions

@Serializable
data class Position(
    val symbol: String,
    val shares: Int,
    @Serializable(with = LocalDateSerializer::class) val entryDate: LocalDate,
    val entryPricePaise: Long,
    /** The stop in force now (it can have moved up since entry). */
    val stopPaise: Long,
    val lastClosePaise: Long,
    /** (lastClose - entryPrice) x shares, paise. */
    val unrealisedPnlPaise: Long,
)

@Serializable
data class PositionsState(
    override val apiVersion: String,
    @Serializable(with = LocalDateSerializer::class) override val dataAsOf: LocalDate,
    @Serializable(with = LocalDateSerializer::class) override val expectedAsOf: LocalDate,
    override val generatedAt: String,
    val cashPaise: Long,
    val positions: List<Position>,
) : Envelope

// ---------------------------------------------------------------------------------------------------------------- /v1/trades

@Serializable
data class ClosedTrade(
    val symbol: String,
    @Serializable(with = LocalDateSerializer::class) val entryDate: LocalDate,
    @Serializable(with = LocalDateSerializer::class) val exitDate: LocalDate,
    val exitReason: ExitReason,
    /** Profit or loss after costs, paise. */
    val netPnlPaise: Long,
    /** Net P&L divided by the paise risked at entry. */
    val netR: Double,
)

/** Footer figures, computed by the server. */
@Serializable
data class TradeStats(
    val tradeCount: Int,
    val wins: Int,
    val losses: Int,
    /** Wins divided by trades, percent; null when there are no trades. */
    val winRatePct: Double?,
    /** Gross profit divided by gross loss; null when there are no losing trades. */
    val profitFactor: Double?,
)

@Serializable
data class TradesState(
    override val apiVersion: String,
    @Serializable(with = LocalDateSerializer::class) override val dataAsOf: LocalDate,
    @Serializable(with = LocalDateSerializer::class) override val expectedAsOf: LocalDate,
    override val generatedAt: String,
    /** Newest exit first. */
    val trades: List<ClosedTrade>,
    val stats: TradeStats,
) : Envelope
