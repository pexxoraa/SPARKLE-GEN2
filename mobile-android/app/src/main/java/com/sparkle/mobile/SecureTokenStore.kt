package com.sparkle.mobile

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecureTokenStore(context: Context) {
    private val appContext = context.applicationContext
    private val prefs: SharedPreferences =
        appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun save(credentials: Enrollment): Boolean {
        return try {
            val key = getOrCreateKey()
            val payload = JSONObject()
                .put("token", credentials.token)
                .put("device_id", credentials.deviceId)
                .put("name", credentials.name)
                .put("kind", credentials.kind)
                .put("os_name", credentials.osName)
                .put("session_id", credentials.sessionId)

            val cipher = Cipher.getInstance(TRANSFORMATION)
            // IMPORTANT: do not provide an IV here. Android Keystore generates it.
            cipher.init(Cipher.ENCRYPT_MODE, key)

            val ciphertext = cipher.doFinal(payload.toString().toByteArray(Charsets.UTF_8))
            val iv = cipher.iv

            val committed = prefs.edit()
                .clear()
                .putString(KEY_CIPHERTEXT, Base64.encodeToString(ciphertext, Base64.NO_WRAP))
                .putString(KEY_IV, Base64.encodeToString(iv, Base64.NO_WRAP))
                .putString(KEY_DEVICE_ID, credentials.deviceId)
                .putString(KEY_DEVICE_NAME, credentials.name)
                .commit()

            if (!committed) {
                clear()
                return false
            }

            val reread = loadInternal()
            if (reread?.token != credentials.token ||
                reread.deviceId != credentials.deviceId ||
                reread.name != credentials.name ||
                reread.kind != credentials.kind ||
                reread.osName != credentials.osName ||
                reread.sessionId != credentials.sessionId
            ) {
                clear()
                return false
            }

            true
        } catch (_: Exception) {
            clear()
            false
        }
    }

    fun load(): Enrollment? {
        return try {
            val loaded = loadInternal()
            if (loaded == null) clear()
            loaded
        } catch (_: Exception) {
            clear()
            null
        }
    }

    fun updateSessionId(sessionId: String): Boolean {
        val current = loadInternal() ?: return false
        return save(current.copy(sessionId = sessionId))
    }

    fun clear() {
        prefs.edit().clear().commit()
        try {
            KeyStore.getInstance(ANDROID_KEYSTORE).apply {
                load(null)
                if (containsAlias(KEY_ALIAS)) deleteEntry(KEY_ALIAS)
            }
        } catch (_: Exception) {
            // Best effort cleanup; the local preferences are already cleared.
        }
    }

    private fun loadInternal(): Enrollment? {
        val ciphertextText = prefs.getString(KEY_CIPHERTEXT, null) ?: return null
        val ivText = prefs.getString(KEY_IV, null) ?: return null
        val storedDeviceId = prefs.getString(KEY_DEVICE_ID, null) ?: return null
        val storedName = prefs.getString(KEY_DEVICE_NAME, null) ?: return null
        if (ciphertextText.isBlank() || ivText.isBlank()) return null

        val key = getExistingKey() ?: return null
        val cipher = Cipher.getInstance(TRANSFORMATION)
        val iv = Base64.decode(ivText, Base64.NO_WRAP)
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, iv))
        val ciphertext = Base64.decode(ciphertextText, Base64.NO_WRAP)
        val plaintext = cipher.doFinal(ciphertext)
        val json = JSONObject(String(plaintext, Charsets.UTF_8))

        val token = json.optString("token")
        val deviceId = json.optString("device_id")
        val name = json.optString("name")
        val kind = json.optString("kind")
        val osName = json.optString("os_name")
        val sessionId = json.optString("session_id")

        if (token.isBlank() || deviceId.isBlank() || name.isBlank() ||
            deviceId != storedDeviceId || name != storedName
        ) return null

        return Enrollment(token, deviceId, name, kind, osName, sessionId)
    }

    private fun getOrCreateKey(): SecretKey {
        getExistingKey()?.let { return it }
        val generator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            ANDROID_KEYSTORE,
        )
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build(),
        )
        return generator.generateKey()
    }

    private fun getExistingKey(): SecretKey? {
        val store = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        return (store.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.secretKey
    }

    companion object {
        private const val PREFS_NAME = "sparkle_auth"
        private const val KEY_ALIAS = "sparkle_auth_v1"
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val KEY_CIPHERTEXT = "ciphertext"
        private const val KEY_IV = "iv"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_DEVICE_NAME = "device_name"
    }
}
