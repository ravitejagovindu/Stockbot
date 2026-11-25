package com.stockbot.paper

import com.stockbot.paper.data.ApiException
import com.stockbot.paper.data.ErrorCode
import com.stockbot.paper.net.ConnectionTester
import com.stockbot.paper.net.Endpoint
import com.stockbot.paper.net.NetworkPaperRepository
import com.stockbot.paper.net.ResponseCache
import com.stockbot.paper.net.SecretText
import com.stockbot.paper.net.TestResult
import com.stockbot.paper.net.UnreachableException
import com.stockbot.paper.net.UrlConnectionTransport
import com.stockbot.paper.ui.ScreenLoader
import com.stockbot.paper.ui.ScreenState
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** The network repository and the connection test against a real local HTTP server (loopback only) that answers 200, 401, 503, nothing, or too slowly. */
class NetworkRepositoryTest {
    private val token = "SECRET-TOKEN-VALUE-0123456789"
    private val servers = mutableListOf<FakeServer>()
    private val seen: List<FakeServer.Request> get() = servers.flatMap { it.seen }

    private fun serve(handler: (FakeServer.Request, Int) -> FakeServer.Reply): String {
        val s = FakeServer(handler)
        servers.add(s)
        return s.url
    }

    @After fun stopServers() {
        servers.forEach { it.stop() }
    }

    private fun ok(body: String) = FakeServer.Reply.Respond(200, body)
    private fun status(code: Int, body: String) = FakeServer.Reply.Respond(code, body)

    private fun example(name: String) = TestExamples.source.read(name)

    private class MemoryCache : ResponseCache {
        val map = HashMap<String, String>()
        override fun get(name: String) = map[name]
        override fun put(name: String, body: String) { map[name] = body }
    }

    private fun repo(base: String?, cache: ResponseCache = MemoryCache(), timeoutMs: Int = 2000) =
        NetworkPaperRepository({ base?.let { Endpoint(it, SecretText(token)) } }, UrlConnectionTransport(), cache, timeoutMs)

    private fun closedPortUrl(): String {
        val s = FakeServer { _, _ -> FakeServer.Reply.Drop }
        val url = s.url
        s.stop()
        return url
    }

    // ------------------------------------------------------------------------------------------------------------------ 200
    @Test fun a200IsParsedByTheContractParserSentWithTheTokenAndIsNotSample() = runBlocking {
        val base = serve { _, _ -> ok(example("account_trades.json")) }
        val r = repo(base)
        val loaded = r.getAccount()
        assertEquals(20_560_000L, loaded.data.summary.equityPaise)
        assertNull(loaded.offlineGeneratedAt)
        assertFalse(r.isSample)
        assertEquals(1, seen.size)
        assertEquals("GET", seen[0].method)
        assertEquals("/v1/account", seen[0].path)
        assertEquals(token, seen[0].token)
    }

    @Test fun everyScreenAsksItsOwnPathWithGetOnly() = runBlocking {
        val base = serve { req, _ -> ok(example("${req.path.removePrefix("/v1/")}_trades.json")) }
        val r = repo(base)
        r.getToday(); r.getAccount(); r.getPositions(); r.getTrades()
        assertEquals(listOf("/v1/today", "/v1/account", "/v1/positions", "/v1/trades"), seen.map { it.path })
        assertTrue(seen.all { it.method == "GET" && it.token == token })
    }

    @Test fun theJobStatusIsFetchedFromTheJobPathAndKeptForOffline() = runBlocking {
        val cache = MemoryCache()
        val base = serve { _, _ -> ok(example("job_retrying.json")) }
        val loaded = repo(base, cache).getJob()
        assertEquals("RETRYING", loaded.data.today.state.name)
        assertEquals("/v1/job", seen.last().path)
        assertEquals("GET", seen.last().method)
        val offline = repo(closedPortUrl(), cache).getJob()
        assertEquals(offline.data.generatedAt, offline.offlineGeneratedAt)
    }

    @Test fun aGoodBodyIsKeptAsTheLastCopy() = runBlocking {
        val cache = MemoryCache()
        val base = serve { _, _ -> status(200, example("today_signal_day.json")) }
        repo(base, cache).getToday()
        assertEquals(example("today_signal_day.json"), cache.map["today"])
    }

    // ------------------------------------------------------------------------------------------------------------------ errors
    @Test fun a401BecomesUnauthorizedAndTheMessageHasNoToken() = runBlocking {
        val cache = MemoryCache()
        val base = serve { _, _ -> status(401, example("error_unauthorized.json")) }
        try {
            repo(base, cache).getToday()
            fail("401 must throw")
        } catch (e: ApiException) {
            assertEquals(ErrorCode.UNAUTHORIZED, e.code)
            assertFalse(e.message!!.contains(token) || e.toString().contains(token))
        }
        assertTrue("an error body is never kept", cache.map.isEmpty())
    }

    @Test fun a503BecomesNotReady() = runBlocking {
        val base = serve { _, _ -> status(503, example("error_not_ready.json")) }
        try {
            repo(base).getAccount()
            fail("503 must throw")
        } catch (e: ApiException) {
            assertEquals(ErrorCode.NOT_READY, e.code)
        }
    }

    @Test fun aServerErrorWithoutAContractBodyIsAServerError() = runBlocking {
        val base = serve { _, _ -> status(500, "<html>oops</html>") }
        try {
            repo(base).getTrades()
            fail("500 must throw")
        } catch (e: ApiException) {
            assertEquals(ErrorCode.SERVER_ERROR, e.code)
            assertFalse(e.message!!.contains("oops"))
        }
    }

    @Test fun anotherApiVersionIsRefusedAndNotKept() = runBlocking {
        val cache = MemoryCache()
        val base = serve { _, _ -> status(200, example("today_empty.json").replace("\"apiVersion\": \"1\"", "\"apiVersion\": \"2\"")) }
        try {
            repo(base, cache).getToday()
            fail("version 2 must be refused")
        } catch (e: ApiException) {
            assertTrue(e.message!!.contains("2"))
        }
        assertTrue(cache.map.isEmpty())
    }

    @Test fun nothingConfiguredIsAnUnauthorizedCalmError() = runBlocking {
        try {
            repo(null).getToday()
            fail("no endpoint must throw")
        } catch (e: ApiException) {
            assertEquals(ErrorCode.UNAUTHORIZED, e.code)
        }
    }

    @Test fun aRedirectIsNotFollowed() = runBlocking {
        val base = serve { _, _ -> FakeServer.Reply.Respond(302, "", headers = mapOf("Location" to "http://127.0.0.1:1/elsewhere")) }
        try {
            repo(base).getToday()
            fail("a redirect is an error")
        } catch (e: ApiException) {
            assertEquals(ErrorCode.SERVER_ERROR, e.code)
        }
        assertEquals(1, seen.size)
    }

    // ------------------------------------------------------------------------------------------------------------------ retry, timeout, unreachable
    @Test fun oneRetryAfterANetworkErrorThenSuccess() = runBlocking {
        val base = serve { _, n -> if (n == 1) FakeServer.Reply.Drop else ok(example("positions_positions.json")) }
        val loaded = repo(base).getPositions()
        assertEquals(4, loaded.data.positions.size)
        assertEquals("one failed try and one retry", 2, seen.size)
    }

    @Test fun aSlowServerTimesOutAfterOneRetryAndNoCopyIsAnUnreachableError() = runBlocking {
        val base = serve { _, _ -> FakeServer.Reply.Respond(200, example("today_empty.json"), delayMs = 1500) }
        val t0 = System.currentTimeMillis()
        try {
            repo(base, timeoutMs = 300).getToday()
            fail("a timeout with no copy must throw")
        } catch (e: UnreachableException) {
            assertFalse(e.message!!.contains(token))
        }
        assertEquals("tried twice, then gave up", 2, seen.size)
        assertTrue("8 s timeouts are the default, this test used 300 ms", System.currentTimeMillis() - t0 < 5_000)
    }

    @Test fun theDefaultTimeoutIsEightSeconds() {
        assertEquals(8_000, com.stockbot.paper.net.TIMEOUT_MS)
    }

    @Test fun aClosedPortIsUnreachable() = runBlocking {
        try {
            repo(closedPortUrl()).getAccount()
            fail("refused connection must throw")
        } catch (e: UnreachableException) {
            // expected
        }
    }

    // ------------------------------------------------------------------------------------------------------------------ the cache fallback
    @Test fun whenTheLaptopCannotBeReachedTheLastCopyIsShownWithItsGeneratedAt() = runBlocking {
        val cache = MemoryCache()
        val base = serve { _, _ -> status(200, example("account_deep_drawdown.json")) }
        repo(base, cache).getAccount()                       // a good answer is kept
        val offline = repo(closedPortUrl(), cache).getAccount()
        assertEquals(17_940_000L, offline.data.summary.equityPaise)
        assertEquals(offline.data.generatedAt, offline.offlineGeneratedAt)
        assertNotNull(offline.offlineGeneratedAt)
    }

    @Test fun theScreenLoaderTurnsTheFallbackIntoContentWithTheOfflineLineAndAnErrorWhenThereIsNoCopy() = runBlocking {
        val cache = MemoryCache()
        val base = serve { _, _ -> status(200, example("trades_trades.json")) }
        repo(base, cache).getTrades()
        val withCopy = ScreenLoader(repo(closedPortUrl(), cache)).trades()
        assertTrue(withCopy is ScreenState.Content && withCopy.offlineAt == withCopy.data.generatedAt)
        val noCopy = ScreenLoader(repo(closedPortUrl(), MemoryCache())).trades()
        assertEquals(ScreenState.Error(ScreenLoader.ERROR_MESSAGE), noCopy)
    }

    @Test fun anUnreadableKeptCopyIsNotShown() = runBlocking {
        val cache = MemoryCache().also { it.put("today", "not json") }
        try {
            repo(closedPortUrl(), cache).getToday()
            fail("a broken copy must not be shown")
        } catch (e: UnreachableException) {
            // expected
        }
    }

    @Test fun aReachableServerWithAnErrorDoesNotFallBackToTheCopy() = runBlocking {
        val cache = MemoryCache().also { it.put("account", example("account_trades.json")) }
        val base = serve { _, _ -> status(401, example("error_unauthorized.json")) }
        try {
            repo(base, cache).getAccount()
            fail("a wrong token must be shown as an error, not hidden behind old data")
        } catch (e: ApiException) {
            assertEquals(ErrorCode.UNAUTHORIZED, e.code)
        }
    }

    // ------------------------------------------------------------------------------------------------------------------ Test connection
    private fun tester() = ConnectionTester(UrlConnectionTransport(), timeoutMs = 400, allowed = { true })

    @Test fun testConnectionConnected() {
        val base = serve { _, _ -> status(200, example("health_ok.json")) }
        val r = tester().test(base, SecretText(token))
        assertEquals("Connected. Data as of 23 Nov 2026.", r.line)
        assertTrue(r is TestResult.Connected)
        assertEquals("/v1/health", seen.last().path)
        assertEquals(token, seen.last().token)
    }

    @Test fun testConnectionWrongTokenUnreachableNotReadyAndOther() {
        assertEquals(TestResult.WrongToken, tester().test(serve { _, _ -> status(401, example("error_unauthorized.json")) }, SecretText(token)))
        assertEquals(TestResult.NotReady, tester().test(serve { _, _ -> status(503, example("error_not_ready.json")) }, SecretText(token)))
        assertEquals(TestResult.NotReady, tester().test(serve { _, _ -> status(200, example("health_ok.json").replace("\"ok\"", "\"not_ready\"")) }, SecretText(token)))
        assertEquals(TestResult.Unreachable, tester().test(closedPortUrl(), SecretText(token)))
        assertEquals(TestResult.Unreachable, tester().test(serve { _, _ -> FakeServer.Reply.Respond(200, "{}", delayMs = 1200) }, SecretText(token)))
        assertEquals(TestResult.Other, tester().test(serve { _, _ -> status(418, "teapot") }, SecretText(token)))
    }

    @Test fun testConnectionLinesAreCalmOneLiners() {
        val lines = listOf(TestResult.WrongToken, TestResult.Unreachable, TestResult.NotReady, TestResult.BadAddress, TestResult.NoToken, TestResult.Other).map { it.line }
        lines.forEach { assertTrue(it, !it.contains("!") && !it.lowercase().contains("please") && !it.contains("\n")) }
        assertEquals("The token was not accepted.", TestResult.WrongToken.line)
        assertEquals("Can't reach your laptop.", TestResult.Unreachable.line)
    }

    @Test fun testConnectionNeedsAToken() {
        assertEquals(TestResult.NoToken, tester().test("http://127.0.0.1:9", null))
        assertEquals(TestResult.NoToken, tester().test("http://127.0.0.1:9", SecretText("  ")))
        assertEquals(0, seen.size)
    }

    @Test fun testConnectionRefusesPlainHttpOutsideTheTailscaleNames() {
        val real = ConnectionTester(UrlConnectionTransport())
        assertEquals(TestResult.BadAddress, real.test("http://example.com", SecretText(token)))
        assertEquals(TestResult.BadAddress, real.test("http://192.168.1.20:8765", SecretText(token)))
        assertEquals(0, seen.size)
    }
}
