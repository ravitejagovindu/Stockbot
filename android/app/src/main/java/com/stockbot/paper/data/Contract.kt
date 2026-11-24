package com.stockbot.paper.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/**
 * Parsing of the API's JSON. The mock repository and the later network repository both go through this, so a mock screen proves the real parsing.
 * Unknown keys are ignored and unknown enum values become OTHER (see the enum serialisers), so a newer server does not crash this app.
 */
object Contract {
    val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    fun today(text: String): TodayState = decode(text) { json.decodeFromString(TodayState.serializer(), it) }
    fun account(text: String): AccountSnapshot = decode(text) { json.decodeFromString(AccountSnapshot.serializer(), it) }
    fun positions(text: String): PositionsState = decode(text) { json.decodeFromString(PositionsState.serializer(), it) }
    fun trades(text: String): TradesState = decode(text) { json.decodeFromString(TradesState.serializer(), it) }
    fun health(text: String): HealthResponse = decode(text) { json.decodeFromString(HealthResponse.serializer(), it) }

    /** The error body of a non-200 response. */
    fun error(text: String): ApiException {
        val e = json.decodeFromString(ErrorResponse.serializer(), text).error
        return ApiException(e.code, e.message)
    }

    private fun <T : Envelope> decode(text: String, parse: (String) -> T): T {
        val unreadable = ApiException(ErrorCode.SERVER_ERROR, "The response could not be read.")
        val isError = try {
            json.parseToJsonElement(text).jsonObject.containsKey("error")
        } catch (e: Exception) {
            throw unreadable
        }
        if (isError) throw error(text)
        val r = try {
            parse(text)
        } catch (e: Exception) {
            throw unreadable
        }
        if (r.apiVersion != API_VERSION) throw ApiException(ErrorCode.SERVER_ERROR, "This app does not support API version ${r.apiVersion}.")
        return r
    }
}

/** The "Updated N days ago" rule: shown only when the data is older than the last trading day on which data is expected. */
object Freshness {
    /** Calendar days from [dataAsOf] to [expectedAsOf] when the data is behind, otherwise null. */
    fun daysBehind(dataAsOf: LocalDate, expectedAsOf: LocalDate): Int? =
        if (dataAsOf.isBefore(expectedAsOf)) ChronoUnit.DAYS.between(dataAsOf, expectedAsOf).toInt() else null

    fun daysBehind(e: Envelope): Int? = daysBehind(e.dataAsOf, e.expectedAsOf)

    /** "Updated 4 days ago", "Updated 1 day ago", or null when the data is current. */
    fun line(e: Envelope): String? = daysBehind(e)?.let { if (it == 1) "Updated 1 day ago" else "Updated $it days ago" }
}
