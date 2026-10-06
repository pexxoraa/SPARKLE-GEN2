#!/usr/bin/env bash
set -euo pipefail

cd "${SPARKLE_GEN2_ROOT:-$HOME/SPARKLE-GEN2}"

if [[ -e mobile-android ]]; then
  echo "ERROR: mobile-android already exists. Refusing to overwrite it."
  exit 1
fi

mkdir -p mobile-android/app/src/main/java/com/sparkle/mobile
mkdir -p mobile-android/app/src/main/res/xml
mkdir -p mobile-android/app/src/main/res/values
mkdir -p mobile-android/app/src/androidTest/java/com/sparkle/mobile/core
mkdir -p mobile-android/app/src/androidTest/java/com/sparkle/mobile/ui/main

cat > mobile-android/settings.gradle.kts <<'EOF'
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "sparkle-mobile"
include(":app")
EOF

cat > mobile-android/build.gradle.kts <<'EOF'
plugins {
    id("com.android.application") version "9.0.1" apply false
}
EOF

cat > mobile-android/gradle.properties <<'EOF'
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
android.nonTransitiveRClass=true
EOF

cat > mobile-android/.gitignore <<'EOF'
*.iml
.gradle
/local.properties
/.idea
/build
/captures
.externalNativeBuild
.cxx
EOF

cat > mobile-android/app/.gitignore <<'EOF'
/build
EOF

cat > mobile-android/app/build.gradle.kts <<'EOF'
plugins {
    id("com.android.application")
}

android {
    namespace = "com.sparkle.mobile"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.sparkle.mobile"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")

    androidTestImplementation("androidx.test:core:1.7.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
EOF

cat > mobile-android/app/src/main/res/values/strings.xml <<'EOF'
<resources>
    <string name="app_name">SPARKLE</string>
    <string name="default_core_url">http://127.0.0.1:8787</string>
</resources>
EOF

cat > mobile-android/app/src/main/res/values/ids.xml <<'EOF'
<resources>
    <item name="core_url_input" type="id" />
    <item name="device_name_input" type="id" />
    <item name="pair_code_input" type="id" />
    <item name="test_core_button" type="id" />
    <item name="pair_button" type="id" />
    <item name="forget_button" type="id" />
    <item name="chat_input" type="id" />
    <item name="send_button" type="id" />
    <item name="status_text" type="id" />
    <item name="chat_log" type="id" />
</resources>
EOF

cat > mobile-android/app/src/main/res/xml/network_security_config.xml <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="false" />
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="false">127.0.0.1</domain>
        <domain includeSubdomains="false">localhost</domain>
    </domain-config>
</network-security-config>
EOF

cat > mobile-android/app/src/main/res/xml/backup_rules.xml <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<full-backup-content>
    <exclude domain="sharedpref" path="sparkle_auth.xml" />
</full-backup-content>
EOF

cat > mobile-android/app/src/main/res/xml/data_extraction_rules.xml <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<data-extraction-rules>
    <cloud-backup>
        <exclude domain="sharedpref" path="sparkle_auth.xml" />
    </cloud-backup>
    <device-transfer>
        <exclude domain="sharedpref" path="sparkle_auth.xml" />
    </device-transfer>
</data-extraction-rules>
EOF

cat > mobile-android/app/src/main/AndroidManifest.xml <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />

    <application
        android:allowBackup="true"
        android:fullBackupContent="@xml/backup_rules"
        android:dataExtractionRules="@xml/data_extraction_rules"
        android:label="@string/app_name"
        android:networkSecurityConfig="@xml/network_security_config"
        android:supportsRtl="true"
        android:theme="@android:style/Theme.Material.NoActionBar"
        android:usesCleartextTraffic="false">

        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
EOF

cat > mobile-android/app/src/main/java/com/sparkle/mobile/SparkleApi.kt <<'EOF'
package com.sparkle.mobile

import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

object CoreUrlValidator {
    fun validate(raw: String): String {
        val value = raw.trim()
        require(value.isNotEmpty()) { "Core URL is required" }

        val uri = URI(value)
        val scheme = uri.scheme?.lowercase() ?: throw IllegalArgumentException("Core URL needs http or https")
        require(scheme == "http" || scheme == "https") { "Core URL must use http or https" }
        require(uri.userInfo == null) { "Core URL must not contain credentials" }
        require(uri.rawQuery == null) { "Core URL must not contain a query" }
        require(uri.rawFragment == null) { "Core URL must not contain a fragment" }
        require(uri.rawPath.isNullOrEmpty() || uri.rawPath == "/") { "Core URL must not contain a path prefix" }

        val host = uri.host?.lowercase() ?: throw IllegalArgumentException("Core URL host is required")
        val port = uri.port

        if (scheme == "http") {
            require(host == "127.0.0.1" || host == "localhost") {
                "Cleartext HTTP is allowed only for the development loopback target"
            }
            require(port == 8787) {
                "The development loopback Core must use port 8787"
            }
        }

        val authority = uri.rawAuthority ?: throw IllegalArgumentException("Core URL authority is required")
        return "$scheme://$authority"
    }
}

data class Enrollment(
    val token: String,
    val deviceId: String,
    val name: String,
    val kind: String,
    val osName: String,
    val sessionId: String = "",
)

class SparkleApi(rawBaseUrl: String) {
    private val baseUrl = CoreUrlValidator.validate(rawBaseUrl)

private fun request(
        method: String,
        path: String,
        body: JSONObject? = null,
        token: String? = null,
    ): Pair<Int, JSONObject> {
        val requestBytes = body?.toString()?.toByteArray(Charsets.UTF_8)

        val connection = (URL(baseUrl + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10_000
            readTimeout = 60_000
            useCaches = false
            doInput = true
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Cache-Control", "no-store")
            setRequestProperty("Connection", "close")

            if (token != null) {
                setRequestProperty("Authorization", "Bearer $token")
            }

            if (requestBytes != null) {
                doOutput = true
                setFixedLengthStreamingMode(requestBytes.size)
                setRequestProperty(
                    "Content-Type",
                    "application/json; charset=utf-8",
                )
            }
        }

        try {
            if (requestBytes != null) {
                connection.outputStream.use { output ->
                    output.write(requestBytes)
                }
            }

            val code = connection.responseCode
            val stream =
                if (code in 200..299) connection.inputStream
                else connection.errorStream

            val text =
                if (stream == null) {
                    "{}"
                } else {
                    BufferedReader(
                        InputStreamReader(stream, Charsets.UTF_8)
                    ).use { it.readText() }
                }

            val json =
                if (text.isBlank()) JSONObject()
                else JSONObject(text)

            if (code !in 200..299) {
                throw SparkleApiException(
                    code,
                    json.optString("error").ifBlank { "HTTP $code" },
                )
            }

            return code to json
        } finally {
            connection.disconnect()
        }
    }

    fun health(): JSONObject = request("GET", "/health").second

    fun enroll(code: String, name: String): Enrollment {
        // Normalize human-entered/copied pairing codes before sending them.
        val normalizedCode = code
            .trim()
            .replace('\u2010', '-')
            .replace('\u2011', '-')
            .replace('\u2012', '-')
            .replace('\u2013', '-')
            .replace('\u2014', '-')
            .replace('\u2212', '-')
            .replace(Regex("\\s+"), "")
            .uppercase()

        val body = JSONObject()
            .put("code", normalizedCode)
            .put("name", name.trim())
            .put("kind", "android")
            .put("os", "Android")
            .put(
                "capabilities",
                JSONArray(listOf("conversation", "notifications", "approvals", "task_status", "device_management", "artifacts")),
            )

        val (status, response) = request("POST", "/api/enroll", body)
        require(status == 201) { "Unexpected enrollment status: $status" }

        val device = response.getJSONObject("device")
        val token = response.getString("token")
        return Enrollment(
            token = token,
            deviceId = device.getString("device_id"),
            name = device.optString("name", name.trim()),
            kind = device.optString("kind", "android"),
            osName = device.optString("os_name", "Android"),
        )
    }

    fun latestSessionId(token: String): String? {
        val sessions = request("GET", "/api/sessions", token = token).second.optJSONArray("sessions") ?: return null
        var latestId: String? = null
        var latestStamp = ""
        for (i in 0 until sessions.length()) {
            val row = sessions.optJSONObject(i) ?: continue
            val id = row.optString("session_id").ifBlank { continue }
            val stamp = row.optString("updated_at").ifBlank { row.optString("created_at") }
            if (latestId == null || stamp > latestStamp) {
                latestId = id
                latestStamp = stamp
            }
        }
        return latestId
    }

    fun chat(token: String, text: String, sessionId: String?): Pair<String, String> {
        val body = JSONObject().put("text", text.trim())
        if (!sessionId.isNullOrBlank()) body.put("session_id", sessionId)
        val response = request("POST", "/api/chat", body, token).second
        return response.getString("session_id") to response.optString("message")
            .ifBlank { response.optString("result") }
    }

    fun logout(token: String) {
        request("POST", "/api/logout", JSONObject(), token)
    }
}

class SparkleApiException(val statusCode: Int, override val message: String) : Exception(message)
EOF

cat > mobile-android/app/src/main/java/com/sparkle/mobile/SecureTokenStore.kt <<'EOF'
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
EOF

cat > mobile-android/app/src/main/java/com/sparkle/mobile/MainActivity.kt <<'EOF'
package com.sparkle.mobile

import android.graphics.Typeface
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : android.app.Activity() {
    private lateinit var coreUrl: EditText
    private lateinit var deviceName: EditText
    private lateinit var pairCode: EditText
    private lateinit var testButton: Button
    private lateinit var pairButton: Button
    private lateinit var forgetButton: Button
    private lateinit var chatInput: EditText
    private lateinit var sendButton: Button
    private lateinit var status: TextView
    private lateinit var chatLog: TextView
    private lateinit var pairingSection: LinearLayout
    private lateinit var chatSection: LinearLayout

    private val executor = Executors.newCachedThreadPool()
    private val pairingFlight = AtomicBoolean(false)
    private val chatFlight = AtomicBoolean(false)
    private lateinit var secureStore: SecureTokenStore
    private var credentials: Enrollment? = null
    private var api: SparkleApi? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        secureStore = SecureTokenStore(this)
        setContentView(buildUi())

        credentials = secureStore.load()
        coreUrl.setText(getPreferences(MODE_PRIVATE).getString(PREF_CORE_URL, getString(R.string.default_core_url)))

        if (credentials == null) {
            showPairing()
        } else {
            showPaired(credentials!!)
        }
    }

    private fun buildUi(): View {
        val scroll = ScrollView(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        scroll.addView(root)

        val title = TextView(this).apply {
            text = "SPARKLE"
            textSize = 30f
            setTypeface(typeface, Typeface.BOLD)
        }
        root.addView(title, lp())

        root.addView(TextView(this).apply {
            text = "Private Personal AI"
            textSize = 16f
        }, lp())

        root.addView(label("Core URL"), lp())
        coreUrl = EditText(this).apply {
            id = R.id.core_url_input
            hint = "http://127.0.0.1:8787"
            isSingleLine = true
        }
        root.addView(coreUrl, lp())

        testButton = Button(this).apply {
            id = R.id.test_core_button
            text = "Test Core"
            setOnClickListener { testCore() }
        }
        root.addView(testButton, lp())

        pairingSection = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        root.addView(pairingSection, lp())

        pairingSection.addView(label("Device name"), lp())
        deviceName = EditText(this).apply {
            id = R.id.device_name_input
            hint = "My Android"
            isSingleLine = true
        }
        pairingSection.addView(deviceName, lp())

        pairingSection.addView(label("One-time enrollment code"), lp())
        pairCode = EditText(this).apply {
            id = R.id.pair_code_input
            hint = "AB12-CD34-EF56"
            isSingleLine = true
        }
        pairingSection.addView(pairCode, lp())

        pairButton = Button(this).apply {
            id = R.id.pair_button
            text = "Pair with SPARKLE"
            setOnClickListener { pair() }
        }
        pairingSection.addView(pairButton, lp())

        chatSection = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        root.addView(chatSection, lp())

        chatSection.addView(label("Conversation"), lp())
        chatLog = TextView(this).apply {
            id = R.id.chat_log
            textSize = 16f
            setPadding(0, 16, 0, 16)
            text = ""
        }
        chatSection.addView(chatLog, lp())

        chatInput = EditText(this).apply {
            id = R.id.chat_input
            hint = "Message SPARKLE"
            minLines = 2
        }
        chatSection.addView(chatInput, lp())

        sendButton = Button(this).apply {
            id = R.id.send_button
            text = "Send"
            setOnClickListener { sendChat() }
        }
        chatSection.addView(sendButton, lp())

        forgetButton = Button(this).apply {
            id = R.id.forget_button
            text = "Forget this device"
            setOnClickListener { forgetDevice() }
        }
        chatSection.addView(forgetButton, lp())

        status = TextView(this).apply {
            id = R.id.status_text
            textSize = 14f
            setPadding(0, 24, 0, 0)
        }
        root.addView(status, lp())

        return scroll
    }

    private fun lp(): LinearLayout.LayoutParams = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { bottomMargin = 16 }

    private fun label(text: String): TextView = TextView(this).apply {
        this.text = text
        textSize = 14f
        setTypeface(typeface, Typeface.BOLD)
    }

    private fun showPairing() {
        pairingSection.visibility = View.VISIBLE
        chatSection.visibility = View.GONE
        forgetButton.visibility = View.GONE
        status.text = "Not paired."
    }

    private fun showPaired(value: Enrollment) {
        pairingSection.visibility = View.GONE
        chatSection.visibility = View.VISIBLE
        forgetButton.visibility = View.VISIBLE
        status.text = "Paired as ${value.name} (${value.osName})"
        appendChat("Paired device: ${value.name}")
    }

    private fun saveCoreUrl() {
        getPreferences(MODE_PRIVATE).edit()
            .putString(PREF_CORE_URL, coreUrl.text.toString().trim())
            .apply()
    }

    private fun buildApi(): SparkleApi {
        saveCoreUrl()
        return SparkleApi(coreUrl.text.toString())
    }

    private fun testCore() {
        if (pairingFlight.get() || chatFlight.get()) return
        status.text = "Testing Core…"
        executor.execute {
            try {
                val health = buildApi().health()
                runOnUiThread { status.text = "Core reachable: ${health.optString("service", "sparkle-personal-core")}" }
            } catch (exc: Exception) {
                runOnUiThread { status.text = "Core test failed: ${safeError(exc)}" }
            }
        }
    }

    private fun pair() {
        if (!pairingFlight.compareAndSet(false, true)) return

        val code = pairCode.text.toString().trim()
        val name = deviceName.text.toString().trim().ifBlank { "My Android" }
        if (code.isBlank()) {
            pairingFlight.set(false)
            status.text = "Enter the one-time enrollment code."
            return
        }

        pairButton.isEnabled = false
        status.text = "Pairing…"

        executor.execute {
            try {
                val candidateApi = buildApi()
                val enrolled = candidateApi.enroll(code, name)

                // The server has now consumed the enrollment code. Never replay it.
                if (!secureStore.save(enrolled)) {
                    runOnUiThread {
                        pairCode.setText("")
                        status.text = "Enrollment reached Core, but secure local persistence failed. Generate a fresh one-time code."
                    }
                    return@execute
                }

                val latestSession = runCatching { candidateApi.latestSessionId(enrolled.token) }.getOrNull()
                val persisted = if (!latestSession.isNullOrBlank()) {
                    val updated = enrolled.copy(sessionId = latestSession)
                    if (!secureStore.save(updated)) {
                        runOnUiThread {
                            pairCode.setText("")
                            secureStore.clear()
                            status.text = "Enrollment completed, but secure session persistence failed. Generate a fresh one-time code."
                        }
                        return@execute
                    }
                    updated
                } else {
                    enrolled
                }

                credentials = persisted
                api = candidateApi
                runOnUiThread {
                    pairCode.setText("")
                    showPaired(persisted)
                }
            } catch (exc: Exception) {
                runOnUiThread {
                    pairCode.setText("")
                    status.text = "Pairing failed: ${safeError(exc)}"
                }
            } finally {
                runOnUiThread { pairButton.isEnabled = true }
                pairingFlight.set(false)
            }
        }
    }

    private fun sendChat() {
        val current = credentials ?: run {
            status.text = "Pair this device first."
            return
        }
        if (!chatFlight.compareAndSet(false, true)) return

        val text = chatInput.text.toString().trim()
        if (text.isBlank()) {
            chatFlight.set(false)
            status.text = "Enter a message."
            return
        }

        sendButton.isEnabled = false
        appendChat("You: $text")
        chatInput.setText("")
        status.text = "Sending…"

        executor.execute {
            try {
                val candidateApi = api ?: buildApi().also { api = it }
                val (sessionId, reply) = candidateApi.chat(current.token, text, current.sessionId.ifBlank { null })
                val updated = current.copy(sessionId = sessionId)
                if (!secureStore.save(updated)) {
                    runOnUiThread {
                        status.text = "Message completed, but session persistence failed."
                        appendChat("SPARKLE: $reply")
                    }
                } else {
                    credentials = updated
                    runOnUiThread {
                        status.text = "Connected"
                        appendChat("SPARKLE: $reply")
                    }
                }
            } catch (exc: Exception) {
                runOnUiThread { status.text = "Chat failed: ${safeError(exc)}" }
            } finally {
                runOnUiThread { sendButton.isEnabled = true }
                chatFlight.set(false)
            }
        }
    }

    private fun forgetDevice() {
        val current = credentials
        if (current == null) {
            showPairing()
            return
        }

        status.text = "Forgetting device…"
        executor.execute {
            runCatching { (api ?: buildApi()).logout(current.token) }
            secureStore.clear()
            credentials = null
            api = null
            runOnUiThread {
                chatLog.text = ""
                showPairing()
            }
        }
    }

    private fun appendChat(text: String) {
        runOnUiThread {
            val current = chatLog.text?.toString().orEmpty()
            chatLog.text = if (current.isBlank()) text else "$current\n\n$text"
        }
    }

    private fun safeError(exc: Exception): String =
        exc.message?.take(200)?.ifBlank { exc::class.java.simpleName } ?: exc::class.java.simpleName

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    companion object {
        private const val PREF_CORE_URL = "core_url"
    }
}
EOF

cat > mobile-android/app/src/androidTest/java/com/sparkle/mobile/core/SecureTokenStoreInstrumentedTest.kt <<'EOF'
package com.sparkle.mobile.core

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.sparkle.mobile.Enrollment
import com.sparkle.mobile.SecureTokenStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SecureTokenStoreInstrumentedTest {
    private lateinit var context: Context
    private lateinit var store: SecureTokenStore

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        store = SecureTokenStore(context)
        store.clear()
    }

    @Test
    fun credential_round_trip_and_complete_identity_verification() {
        val expected = Enrollment(
            token = "test-device-token",
            deviceId = "device-1",
            name = "Phone",
            kind = "android",
            osName = "Android",
            sessionId = "session-1",
        )

        assertTrue(store.save(expected))
        assertEquals(expected, store.load())
    }

    @Test
    fun clear_removes_complete_local_pairing_identity() {
        val value = Enrollment("token", "device", "Phone", "android", "Android")
        assertTrue(store.save(value))
        store.clear()
        assertNull(store.load())
    }

    @Test
    fun incomplete_persisted_identity_is_rejected() {
        context.getSharedPreferences("sparkle_auth", Context.MODE_PRIVATE)
            .edit()
            .putString("device_id", "device-only")
            .commit()

        assertNull(store.load())
    }
}
EOF

cat > mobile-android/app/src/androidTest/java/com/sparkle/mobile/ui/main/MainScreenTest.kt <<'EOF'
package com.sparkle.mobile.ui.main

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.sparkle.mobile.MainActivity
import com.sparkle.mobile.R
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainScreenTest {
    @Test
    fun pairing_and_core_controls_are_present() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assertNotNull(activity.findViewById(R.id.core_url_input))
                assertNotNull(activity.findViewById(R.id.device_name_input))
                assertNotNull(activity.findViewById(R.id.pair_code_input))
                assertNotNull(activity.findViewById(R.id.test_core_button))
                assertNotNull(activity.findViewById(R.id.pair_button))
            }
        }
    }
}
EOF

# Generate a Gradle 9.1.0 wrapper from the distribution already cached on this machine.
GRADLE_BIN="$(find "$HOME/.gradle/wrapper/dists/gradle-9.1.0-bin" -type f -path '*/gradle-9.1.0/bin/gradle' 2>/dev/null | head -1)"
if [[ -z "$GRADLE_BIN" ]]; then
    echo "ERROR: cached Gradle 9.1.0 binary was not found under ~/.gradle/wrapper/dists/gradle-9.1.0-bin"
    exit 1
fi

"$GRADLE_BIN" -p mobile-android wrapper --gradle-version 9.1.0

# Detect Android SDK for this local build. local.properties is ignored.
SDK_DIR="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [[ -z "$SDK_DIR" && -d "$HOME/Android/Sdk" ]]; then
    SDK_DIR="$HOME/Android/Sdk"
fi
if [[ -z "$SDK_DIR" && -d "/opt/android-sdk" ]]; then
    SDK_DIR="/opt/android-sdk"
fi
if [[ -z "$SDK_DIR" ]]; then
    SDKMANAGER="$(command -v sdkmanager || true)"
    if [[ -n "$SDKMANAGER" ]]; then
        SDK_DIR="$(readlink -f "$SDKMANAGER")"
        SDK_DIR="$(dirname "$SDK_DIR")"
        SDK_DIR="$(dirname "$SDK_DIR")"
        SDK_DIR="$(dirname "$SDK_DIR")"
        SDK_DIR="$(dirname "$SDK_DIR")"
    fi
fi
if [[ -z "$SDK_DIR" || ! -d "$SDK_DIR" ]]; then
    echo "ERROR: Android SDK directory could not be detected."
    echo "Set ANDROID_HOME or ANDROID_SDK_ROOT and rerun the script."
    exit 1
fi
printf 'sdk.dir=%s\n' "$SDK_DIR" > mobile-android/local.properties

echo "Fresh mobile-android project created."
echo "SDK: $SDK_DIR"
echo "Next: cd mobile-android && ./gradlew test"
