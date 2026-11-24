package com.stockbot.paper

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import com.stockbot.paper.format.RupeeFormat
import com.stockbot.paper.net.AesGcmBox
import com.stockbot.paper.net.CleartextHosts
import com.stockbot.paper.net.ConnectionSettings
import com.stockbot.paper.net.ConnectionStore
import com.stockbot.paper.net.DEFAULT_SERVER
import com.stockbot.paper.net.SecretText
import com.stockbot.paper.net.cleartextAllowed
import com.stockbot.paper.net.normalizeAddress
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

class ConnectionStoreTest {
    private val token = "SECRET-TOKEN-VALUE-0123456789"
    private lateinit var file: File
    private lateinit var scope: CoroutineScope
    private val key: SecretKey = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    private val box = AesGcmBox { key }

    @Before fun setUp() {
        file = File.createTempFile("conn", ".preferences_pb").also { it.delete() }
        scope = CoroutineScope(Dispatchers.IO + Job())
    }

    @After fun tearDown() {
        scope.cancel()
        file.delete()
    }

    private fun store(b: AesGcmBox = box) = ConnectionStore(PreferenceDataStoreFactory.create(scope = scope, produceFile = { file }), b)

    @Test fun defaultsAreTheTailscaleAddressNoTokenAndSampleOn() = runBlocking {
        val s = store().current()
        assertEquals(DEFAULT_SERVER, s.address)
        assertEquals("http://100.125.195.111:8765", s.address)
        assertNull(s.token)
        assertTrue(s.useSample)
        assertFalse(s.hasToken)
    }

    @Test fun addressTokenAndSwitchAreSavedAndRead() = runBlocking {
        val st = store()
        st.save("http://laptop.tail0118ce.ts.net:8765", SecretText(token))
        st.setUseSample(false)
        val s = st.current()
        assertEquals("http://laptop.tail0118ce.ts.net:8765", s.address)
        assertEquals(token, s.token!!.reveal())
        assertFalse(s.useSample)
        assertTrue(s.hasToken)
    }

    @Test fun savingWithoutATokenKeepsTheStoredOneAndClearRemovesIt() = runBlocking {
        val st = store()
        st.save(DEFAULT_SERVER, SecretText(token))
        st.save("http://100.125.195.111:9000", null)
        assertEquals(token, st.current().token!!.reveal())
        assertEquals("http://100.125.195.111:9000", st.current().address)
        st.clearToken()
        assertNull(st.current().token)
    }

    @Test fun theStoredFileHoldsOnlyTheEncryptedToken() = runBlocking {
        store().save(DEFAULT_SERVER, SecretText(token))
        scope.cancel()                                           // flush and release the file
        val raw = file.readBytes()
        assertTrue(raw.isNotEmpty())
        assertFalse("the token must not be in the file in plain text", String(raw, Charsets.ISO_8859_1).contains(token))
        assertFalse(String(raw, Charsets.ISO_8859_1).contains(token.substring(0, 12)))
    }

    @Test fun aTokenThatCannotBeDecryptedReadsAsNoToken() = runBlocking {
        store().save(DEFAULT_SERVER, SecretText(token))
        // A second DataStore on the same path in one process is refused, so the saved bytes are opened from a copy (as after a restart).
        val copy = File.createTempFile("conn-copy", ".preferences_pb")
        try {
            file.copyTo(copy, overwrite = true)
            val otherKey = AesGcmBox { KeyGenerator.getInstance("AES").apply { init(256) }.generateKey() }
            val s = ConnectionStore(PreferenceDataStoreFactory.create(scope = scope, produceFile = { copy }), otherKey).current()
            assertNull(s.token)
            assertEquals(DEFAULT_SERVER, s.address)
        } finally {
            copy.delete()
        }
    }

    @Test fun twoEncryptionsOfTheSameTokenDiffer() {
        val a = box.encrypt(token.toByteArray())
        val b = box.encrypt(token.toByteArray())
        assertNotEquals(a.toList(), b.toList())
        assertEquals(token, String(box.decrypt(a)))
        assertEquals(token, String(box.decrypt(b)))
    }

    // ------------------------------------------------------------------------------------------------------------------ the token never shows in text
    @Test fun theTokensTextFormNeverShowsTheValue() {
        val secret = SecretText(token)
        assertFalse(secret.toString().contains(token))
        assertFalse("$secret".contains(token))
        val settings = ConnectionSettings(address = DEFAULT_SERVER, token = secret, useSample = false)
        assertFalse(settings.toString().contains(token))
        assertFalse(settings.copy(address = "x").toString().contains(token))
        assertFalse(listOf(secret).toString().contains(token))
        assertFalse(mapOf("t" to secret).toString().contains(token))
        assertEquals(secret, SecretText(token))
    }

    @Test fun theAppSourceNeverLogsAndNeverPrintsTheToken() {
        val root = File("src/main/java")
        assertTrue("the source folder is found from the module directory", root.isDirectory)
        val files = root.walkTopDown().filter { it.extension == "kt" }.toList()
        assertTrue(files.size > 20)
        for (f in files) {
            val text = f.readText()
            assertFalse("${f.name} uses android.util.Log", text.contains("android.util.Log") || Regex("""\bLog\.[dviwe]\(""").containsMatchIn(text))
            assertFalse("${f.name} prints", Regex("""\b(println|print|printStackTrace)\(""").containsMatchIn(text))
        }
    }

    // ------------------------------------------------------------------------------------------------------------------ address rules
    @Test fun normalizeAddressCases() {
        assertEquals("http://100.125.195.111:8765", normalizeAddress("100.125.195.111:8765"))
        assertEquals("http://100.125.195.111:8765", normalizeAddress("  http://100.125.195.111:8765/ "))
        assertEquals("http://laptop.tail0118ce.ts.net:8765", normalizeAddress("laptop.tail0118ce.ts.net:8765"))
        assertEquals("https://example.com", normalizeAddress("https://example.com"))
        assertEquals(DEFAULT_SERVER, normalizeAddress(""))
        assertNull(normalizeAddress("http://"))
        assertNull(normalizeAddress("http://100.125.195.111:8765/v1/health"))
        assertNull(normalizeAddress("http://100.125.195.111:8765?x=1"))
        assertNull(normalizeAddress("not a url at all"))
    }

    @Test fun plainHttpIsOnlyAllowedForTheTailscaleAddressAndName() {
        assertTrue(cleartextAllowed("http://100.125.195.111:8765"))
        assertTrue(cleartextAllowed("http://laptop.tail0118ce.ts.net:8765"))
        assertTrue(cleartextAllowed("https://anything.example"))
        assertFalse(cleartextAllowed("http://100.125.195.112:8765"))
        assertFalse(cleartextAllowed("http://192.168.1.20:8765"))
        assertFalse(cleartextAllowed("http://example.com"))
        assertFalse(cleartextAllowed("http://localhost:8765"))
        assertFalse(cleartextAllowed("ftp://100.125.195.111"))
    }

    @Test fun theLastSeenTimeIsShownInPlainWords() {
        assertEquals("24 Nov, 19:48", RupeeFormat.dateTime("2026-11-24T19:48:30+05:30"))
        assertEquals("not a time", RupeeFormat.dateTime("not a time"))
    }

    // ------------------------------------------------------------------------------------------------------------------ manifest and network security config
    private fun text(path: String) = File(path).readText()

    @Test fun theNetworkSecurityConfigAllowsPlainHttpOnlyForTheTwoTailscaleNames() {
        val xml = text("src/main/res/xml/network_security_config.xml")
        assertTrue(Regex("""<base-config\s+cleartextTrafficPermitted="false"\s*/>""").containsMatchIn(xml))
        val domains = Regex("""<domain[^>]*>([^<]+)</domain>""").findAll(xml).map { it.groupValues[1].trim() }.toList()
        assertEquals(CleartextHosts.ALL, domains)
        assertEquals(1, Regex("""cleartextTrafficPermitted="true"""").findAll(xml).count())
        assertEquals(2, Regex("""includeSubdomains="false"""").findAll(xml).count())
        assertTrue(domains.none { it.contains("*") || it == "localhost" })
    }

    @Test fun theManifestAsksForInternetAndNothingElseAndUsesTheConfig() {
        val m = text("src/main/AndroidManifest.xml").replace(Regex("<!--.*?-->", RegexOption.DOT_MATCHES_ALL), "")
        val perms = Regex("""<uses-permission[^>]*android:name="([^"]+)"""").findAll(m).map { it.groupValues[1] }.toList()
        assertEquals(listOf("android.permission.INTERNET"), perms)
        assertTrue(m.contains("""android:networkSecurityConfig="@xml/network_security_config""""))
        assertFalse(m.contains("usesCleartextTraffic"))
    }
}
