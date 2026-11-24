package com.stockbot.paper.net

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.net.URI
import java.util.Base64

/** The hosts the network security config allows plain HTTP for (the link is already encrypted by Tailscale). Keep in step with res/xml/network_security_config.xml (a test does). */
object CleartextHosts {
    const val TAILSCALE_IP = "100.125.195.111"
    const val MAGIC_DNS = "laptop.tail0118ce.ts.net"
    val ALL = listOf(TAILSCALE_IP, MAGIC_DNS)
}

const val DEFAULT_SERVER = "http://${CleartextHosts.TAILSCALE_IP}:8765"

/** What the Connection screen edits. The token's text form is hidden (see [SecretText]). */
data class ConnectionSettings(
    val address: String = DEFAULT_SERVER,
    val token: SecretText? = null,
    /** Show the sample data (the contract's examples) instead of the laptop's real figures. On until the owner turns it off. */
    val useSample: Boolean = true,
) {
    val hasToken: Boolean get() = token != null && !token.isBlank()
}

/** "100.125.195.111:8765" becomes "http://100.125.195.111:8765"; a trailing slash is dropped; null when it is not an address. */
fun normalizeAddress(input: String): String? {
    var s = input.trim()
    if (s.isEmpty()) return DEFAULT_SERVER
    if (!s.startsWith("http://", ignoreCase = true) && !s.startsWith("https://", ignoreCase = true)) s = "http://$s"
    s = s.trimEnd('/')
    return try {
        val u = URI(s)
        if (u.host.isNullOrBlank() || (u.path != null && u.path.isNotEmpty()) || u.query != null) null else s
    } catch (e: Exception) {
        null
    }
}

/** Plain HTTP is only allowed for the Tailscale address and name; any other address must use https. */
fun cleartextAllowed(address: String): Boolean {
    val u = try { URI(address) } catch (e: Exception) { return false }
    val scheme = u.scheme?.lowercase()
    return scheme == "https" || (scheme == "http" && u.host in CleartextHosts.ALL)
}

/**
 * Keeps the server address in DataStore and the token encrypted ([SecretBox], AES-GCM with an Android Keystore key). The DataStore file only ever holds the encrypted token.
 * Nothing here logs; a token that cannot be decrypted (the key was lost) reads as no token.
 */
class ConnectionStore(private val dataStore: DataStore<Preferences>, private val box: SecretBox) {
    val settings: Flow<ConnectionSettings> = dataStore.data.map { p ->
        ConnectionSettings(
            address = p[ADDRESS] ?: DEFAULT_SERVER,
            token = p[TOKEN]?.let(::decryptOrNull),
            useSample = p[SAMPLE] ?: true,
        )
    }

    suspend fun current(): ConnectionSettings = settings.first()

    /** Saves the address, and the token when [token] is not null (null keeps the stored one). */
    suspend fun save(address: String, token: SecretText?) {
        dataStore.edit {
            it[ADDRESS] = address
            if (token != null) it[TOKEN] = Base64.getEncoder().encodeToString(box.encrypt(token.reveal().toByteArray(Charsets.UTF_8)))
        }
    }

    suspend fun setUseSample(value: Boolean) {
        dataStore.edit { it[SAMPLE] = value }
    }

    suspend fun clearToken() {
        dataStore.edit { it.remove(TOKEN) }
    }

    private fun decryptOrNull(stored: String): SecretText? = try {
        SecretText(String(box.decrypt(Base64.getDecoder().decode(stored)), Charsets.UTF_8))
    } catch (e: Exception) {
        null
    }

    private companion object {
        val ADDRESS = stringPreferencesKey("server_address")
        val TOKEN = stringPreferencesKey("token_encrypted")
        val SAMPLE = booleanPreferencesKey("use_sample")
    }
}
