package com.stockbot.paper.net

import com.stockbot.paper.data.ApiException
import com.stockbot.paper.data.Contract
import com.stockbot.paper.data.ErrorCode
import com.stockbot.paper.format.RupeeFormat
import java.io.IOException

/** The outcome of "Test connection", each with the one calm line the Connection screen shows. */
sealed interface TestResult {
    val line: String

    data class Connected(val dataAsOf: java.time.LocalDate) : TestResult {
        override val line: String get() = "Connected. Data as of ${RupeeFormat.dateYear(dataAsOf)}."
    }

    data object WrongToken : TestResult {
        override val line = "The token was not accepted."
    }

    data object Unreachable : TestResult {
        override val line = "Can't reach your laptop."
    }

    data object NotReady : TestResult {
        override val line = "The laptop answered, but the data is not ready yet."
    }

    data object BadAddress : TestResult {
        override val line = "That address does not look right. Plain http is only allowed for the Tailscale address."
    }

    data object NoToken : TestResult {
        override val line = "Enter the token first."
    }

    data object Other : TestResult {
        override val line = "The laptop answered with something unexpected."
    }
}

/** Calls GET /v1/health once (with the retry) and turns the answer into a [TestResult]. */
class ConnectionTester(
    private val transport: HttpTransport,
    private val timeoutMs: Int = TIMEOUT_MS,
    private val allowed: (String) -> Boolean = ::cleartextAllowed,
) {
    fun test(address: String, token: SecretText?): TestResult {
        if (!allowed(address)) return TestResult.BadAddress
        if (token == null || token.isBlank()) return TestResult.NoToken
        val headers = mapOf(TOKEN_HEADER to token.reveal())
        val response = try {
            try {
                transport.get("$address/v1/health", headers, timeoutMs)
            } catch (e: IOException) {
                transport.get("$address/v1/health", headers, timeoutMs)
            }
        } catch (e: IOException) {
            return TestResult.Unreachable
        } catch (e: IllegalArgumentException) {
            return TestResult.BadAddress
        }
        if (response.status == 200) {
            return try {
                val h = Contract.health(response.body)
                if (h.status == "ok") TestResult.Connected(h.latestSealedDate ?: h.dataAsOf) else TestResult.NotReady
            } catch (e: ApiException) {
                TestResult.Other
            }
        }
        val code = try { Contract.error(response.body).code } catch (e: Exception) { null }
        return when {
            response.status == 401 || code == ErrorCode.UNAUTHORIZED -> TestResult.WrongToken
            response.status == 503 || code == ErrorCode.NOT_READY -> TestResult.NotReady
            else -> TestResult.Other
        }
    }
}
