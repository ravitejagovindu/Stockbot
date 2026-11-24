package com.stockbot.paper.net

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * A secret string (the access token). Its text form never shows the value, so a stray log line, a toString of a settings object or an exception message cannot leak it.
 * The only way to the value is [reveal], used when the header is set.
 */
class SecretText(private val value: String) {
    fun reveal(): String = value
    fun isBlank(): Boolean = value.isBlank()
    override fun toString(): String = "SecretText(***)"
    override fun equals(other: Any?): Boolean = other is SecretText && other.value == value
    override fun hashCode(): Int = value.hashCode()
}

/** Encrypts and decrypts small secrets. The Android implementation keeps its key in the Android Keystore; tests use a software key. */
interface SecretBox {
    fun encrypt(plain: ByteArray): ByteArray
    fun decrypt(blob: ByteArray): ByteArray
}

/** AES-256-GCM. The stored blob is a 12-byte random IV followed by the ciphertext and tag. */
open class AesGcmBox(private val key: () -> SecretKey) : SecretBox {
    override fun encrypt(plain: ByteArray): ByteArray {
        // The cipher makes its own random IV: the Android Keystore refuses a caller-provided IV for encryption.
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val iv = cipher.iv
        check(iv.size == IV_BYTES) { "unexpected IV size" }
        return iv + cipher.doFinal(plain)
    }

    override fun decrypt(blob: ByteArray): ByteArray {
        require(blob.size > IV_BYTES) { "stored secret is too short" }
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(TAG_BITS, blob.copyOfRange(0, IV_BYTES)))
        return cipher.doFinal(blob, IV_BYTES, blob.size - IV_BYTES)
    }

    private companion object {
        const val TRANSFORM = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val TAG_BITS = 128
    }
}

/** The key lives in the Android Keystore under [alias]; it is created on first use and never leaves the secure hardware or the keystore process. */
class KeystoreSecretBox(private val alias: String = "stockbot_paper_token_key") : AesGcmBox({ loadOrCreate(alias) }) {
    private companion object {
        fun loadOrCreate(alias: String): SecretKey {
            val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (ks.getKey(alias, null) as? SecretKey)?.let { return it }
            val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            gen.init(
                KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
            return gen.generateKey()
        }
    }
}
