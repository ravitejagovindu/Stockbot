package com.stockbot.paper.net

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

data class HttpResponse(val status: Int, val body: String)

/** One GET with headers. Throws [IOException] for anything that is a network failure (no route, refused, reset, timeout). */
fun interface HttpTransport {
    @Throws(IOException::class)
    fun get(url: String, headers: Map<String, String>, timeoutMs: Int): HttpResponse
}

/** Plain `HttpURLConnection`: no new dependency. Redirects are not followed, nothing is cached, the body is capped at 8 MB. Never logs. */
class UrlConnectionTransport : HttpTransport {
    override fun get(url: String, headers: Map<String, String>, timeoutMs: Int): HttpResponse {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "GET"
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.useCaches = false
            conn.instanceFollowRedirects = false
            conn.setRequestProperty("Accept", "application/json")
            headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }
            val status = conn.responseCode
            val stream = if (status in 200..399) conn.inputStream else conn.errorStream
            return HttpResponse(status, stream?.use { readCapped(it) } ?: "")
        } finally {
            conn.disconnect()
        }
    }

    private fun readCapped(s: java.io.InputStream): String {
        val out = ByteArrayOutputStream()
        val buf = ByteArray(8192)
        while (true) {
            val n = s.read(buf)
            if (n < 0) break
            out.write(buf, 0, n)
            if (out.size() > MAX_BYTES) throw IOException("response too large")
        }
        return out.toString(Charsets.UTF_8.name())
    }

    private companion object {
        const val MAX_BYTES = 8 * 1024 * 1024
    }
}

const val TIMEOUT_MS = 8_000
const val TOKEN_HEADER = "X-Paper-Token"
