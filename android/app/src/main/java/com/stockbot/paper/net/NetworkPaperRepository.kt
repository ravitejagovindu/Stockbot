package com.stockbot.paper.net

import com.stockbot.paper.data.AccountSnapshot
import com.stockbot.paper.data.ApiException
import com.stockbot.paper.data.Contract
import com.stockbot.paper.data.Envelope
import com.stockbot.paper.data.ErrorCode
import com.stockbot.paper.data.JobStatus
import com.stockbot.paper.data.Loaded
import com.stockbot.paper.data.PaperRepository
import com.stockbot.paper.data.PositionsState
import com.stockbot.paper.data.TodayState
import com.stockbot.paper.data.TradesState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException

/** The laptop could not be reached (after one retry) and there is no kept copy to show. */
class UnreachableException : IOException("The laptop could not be reached.")

/** Where to ask and with which token. Null when nothing is configured yet. */
class Endpoint(val baseUrl: String, val token: SecretText)

/** The last good JSON body per endpoint, kept on the phone. A body is saved only after it parsed. It holds no token (responses never carry one). */
interface ResponseCache {
    fun get(name: String): String?
    fun put(name: String, body: String)
}

class FileResponseCache(private val dir: File) : ResponseCache {
    override fun get(name: String): String? = try {
        File(dir, "$name.json").takeIf { it.isFile }?.readText(Charsets.UTF_8)
    } catch (e: IOException) {
        null
    }

    override fun put(name: String, body: String) {
        try {
            dir.mkdirs()
            val tmp = File(dir, "$name.json.tmp")
            tmp.writeText(body, Charsets.UTF_8)
            if (!tmp.renameTo(File(dir, "$name.json"))) tmp.delete()
        } catch (e: IOException) {
            // a cache that cannot be written is not an error for the screen
        }
    }
}

/**
 * The BFF over Tailscale. Read-only: only GET. 8 s timeouts, header X-Paper-Token, one retry after a network error. The body is parsed by the SAME [Contract] parser as the mock path
 * (apiVersion check and the error body included). When the laptop cannot be reached the last good copy is returned with [Loaded.offlineGeneratedAt] set; with no copy, [UnreachableException] is thrown.
 * Neither the token nor a response body is ever put into an exception message or a log.
 */
class NetworkPaperRepository(
    private val endpoint: () -> Endpoint?,
    private val transport: HttpTransport,
    private val cache: ResponseCache,
    private val timeoutMs: Int = TIMEOUT_MS,
) : PaperRepository {
    override val isSample: Boolean = false

    override suspend fun getToday(): Loaded<TodayState> = load("today", Contract::today)
    override suspend fun getAccount(): Loaded<AccountSnapshot> = load("account", Contract::account)
    override suspend fun getPositions(): Loaded<PositionsState> = load("positions", Contract::positions)
    override suspend fun getTrades(): Loaded<TradesState> = load("trades", Contract::trades)
    override suspend fun getJob(): Loaded<JobStatus> = load("job", Contract::job)

    private suspend fun <T : Envelope> load(name: String, parse: (String) -> T): Loaded<T> = withContext(Dispatchers.IO) {
        val ep = endpoint() ?: throw ApiException(ErrorCode.UNAUTHORIZED, "Set the server and the token on the Connection screen.")
        val response = try {
            getWithRetry("${ep.baseUrl}/v1/$name", ep.token)
        } catch (e: IOException) {
            return@withContext offlineCopy(name, parse) ?: throw UnreachableException()
        }
        if (response.status != 200) throw errorFor(response)
        val data = parse(response.body)                       // throws ApiException for another apiVersion or an unreadable body
        cache.put(name, response.body)
        Loaded(data)
    }

    private fun <T : Envelope> offlineCopy(name: String, parse: (String) -> T): Loaded<T>? {
        val body = cache.get(name) ?: return null
        return try {
            val data = parse(body)
            Loaded(data, data.generatedAt)
        } catch (e: Exception) {
            null
        }
    }

    private fun getWithRetry(url: String, token: SecretText): HttpResponse {
        val headers = mapOf(TOKEN_HEADER to token.reveal())
        return try {
            transport.get(url, headers, timeoutMs)
        } catch (first: IOException) {
            transport.get(url, headers, timeoutMs)            // one retry; a second failure propagates
        }
    }

    internal fun errorFor(r: HttpResponse): ApiException = try {
        Contract.error(r.body)
    } catch (e: Exception) {
        ApiException(ErrorCode.SERVER_ERROR, "The server answered with status ${r.status}.")
    }
}
