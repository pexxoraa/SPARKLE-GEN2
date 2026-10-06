package com.sparkle.mobile

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.webkit.CookieManager
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : Activity() {
    private lateinit var coreUrl: EditText
    private lateinit var deviceName: EditText
    private lateinit var pairCode: EditText
    private lateinit var testButton: Button
    private lateinit var pairButton: Button
    private lateinit var status: TextView
    private lateinit var pairingSection: LinearLayout
    private lateinit var setupRoot: View

    private val executor = Executors.newCachedThreadPool()
    private val pairingFlight = AtomicBoolean(false)
    private lateinit var secureStore: SecureTokenStore
    private var credentials: Enrollment? = null
    private var api: SparkleApi? = null
    private var webView: WebView? = null
    private var uploadCallback: ValueCallback<Array<Uri>>? = null
    private var pendingPermissionRequest: PermissionRequest? = null

    companion object {
        private const val PREF_CORE_URL = "core_url"
        private const val FILE_CHOOSER_REQUEST = 4101
        private const val AUDIO_PERMISSION_REQUEST = 4102
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        secureStore = SecureTokenStore(this)
        credentials = secureStore.load()
        setupRoot = buildPairingUi()
        setContentView(setupRoot)
        coreUrl.setText(getPreferences(MODE_PRIVATE).getString(
            PREF_CORE_URL, getString(R.string.default_core_url)
        ))

        if (credentials == null) {
            showPairing()
        } else {
            validateStoredCredentials(credentials!!)
        }
    }

    private fun buildPairingUi(): View {
        val scroll = ScrollView(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
            setBackgroundColor(Color.rgb(7, 11, 20))
        }
        scroll.addView(root)

        root.addView(TextView(this).apply {
            text = "SPARKLE"
            textSize = 30f
            setTextColor(Color.WHITE)
        }, lp())

        root.addView(TextView(this).apply {
            text = "Private Personal AI"
            textSize = 16f
            setTextColor(Color.LTGRAY)
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

        status = TextView(this).apply {
            id = R.id.status_text
            textSize = 14f
            setTextColor(Color.LTGRAY)
        }
        root.addView(status, lp())
        return scroll
    }

    private fun lp(): LinearLayout.LayoutParams =
        LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = 16 }

    private fun label(text: String): TextView =
        TextView(this).apply {
            this.text = text
            textSize = 14f
            setTextColor(Color.LTGRAY)
        }

    private fun showPairing() {
        webView?.let {
            it.stopLoading()
            it.destroy()
        }
        webView = null
        pairingSection.visibility = View.VISIBLE
        status.text = "Not paired."
        setContentView(setupRoot)
    }

    private fun validateStoredCredentials(value: Enrollment) {
        pairingSection.visibility = View.GONE
        status.text = "Checking saved pairing…"
        executor.execute {
            try {
                val candidateApi = buildApi()
                val valid = candidateApi.validateCredentials(value.token)
                if (valid) {
                    credentials = value
                    api = candidateApi
                    runOnUiThread { prepareWebView(value) }
                } else {
                    secureStore.clear()
                    credentials = null
                    runOnUiThread {
                        pairingSection.visibility = View.VISIBLE
                        status.text = "Saved pairing is no longer valid. Pair this device again."
                    }
                }
            } catch (exc: Exception) {
                // Keep the local login across temporary Core/network outages.
                // Only an explicit 401/403 invalidates the saved session.
                runOnUiThread {
                    credentials = value
                    prepareWebView(value)
                    statusOrToast("Core unavailable; keeping your signed-in session")
                }
            }
        }
    }

    private fun showPaired(value: Enrollment) {
        credentials = value
        pairingSection.visibility = View.GONE
        prepareWebView(value)
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
        if (pairingFlight.get()) return
        status.text = "Testing Core…"
        executor.execute {
            try {
                val health = buildApi().health()
                runOnUiThread {
                    status.text = "Core reachable: ${health.optString(
                        "service", "sparkle-personal-core"
                    )}"
                }
            } catch (exc: Exception) {
                runOnUiThread {
                    status.text = "Core test failed: ${safeError(exc)}"
                }
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
                if (!secureStore.save(enrolled)) {
                    runOnUiThread {
                        pairCode.setText("")
                        status.text =
                            "Enrollment reached Core, but secure local persistence failed. Generate a fresh one-time code."
                    }
                    return@execute
                }

                val latestSession =
                    runCatching { candidateApi.latestSessionId(enrolled.token) }.getOrNull()
                val persisted = if (!latestSession.isNullOrBlank()) {
                    val updated = enrolled.copy(sessionId = latestSession)
                    if (!secureStore.save(updated)) {
                        secureStore.clear()
                        runOnUiThread {
                            pairCode.setText("")
                            status.text =
                                "Enrollment completed, but secure session persistence failed. Generate a fresh one-time code."
                        }
                        return@execute
                    }
                    updated
                } else enrolled

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

    private fun prepareWebView(value: Enrollment) {
        val baseUrl = coreUrl.text.toString().trim().removeSuffix("/")
        getPreferences(MODE_PRIVATE).edit()
            .putString(PREF_CORE_URL, baseUrl)
            .apply()

        val cookies = CookieManager.getInstance()
        cookies.setAcceptCookie(true)
        cookies.setCookie(
            "${baseUrl}/",
            "sparkle_device=${value.token}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Strict"
        )
        cookies.flush()

        val view = WebView(this).apply {
            setBackgroundColor(Color.rgb(7, 11, 20))
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.databaseEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.allowFileAccess = false
            settings.allowContentAccess = true
            settings.mixedContentMode =
                android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
        }

        view.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest
            ): android.webkit.WebResourceResponse? {
                if (request.url.path == "/api/logout" &&
                    request.method.equals("POST", ignoreCase = true)
                ) {
                    executor.execute {
                        secureStore.clear()
                        credentials = null
                    }
                }
                return super.shouldInterceptRequest(view, request)
            }

            override fun onReceivedError(
                view: WebView,
                request: WebResourceRequest,
                error: android.webkit.WebResourceError
            ) {
                if (request.isForMainFrame) {
                    runOnUiThread {
                        val message = error.description?.toString().orEmpty()
                        statusOrToast(message)
                    }
                }
            }
        }

        view.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                uploadCallback?.onReceiveValue(null)
                uploadCallback = filePathCallback
                return try {
                    val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "image/*"
                    }
                    startActivityForResult(intent, FILE_CHOOSER_REQUEST)
                    true
                } catch (_: Exception) {
                    uploadCallback?.onReceiveValue(null)
                    uploadCallback = null
                    false
                }
            }

            override fun onPermissionRequest(request: PermissionRequest) {
                val audio = PermissionRequest.RESOURCE_AUDIO_CAPTURE
                if (!request.resources.contains(audio)) {
                    request.deny()
                    return
                }
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) ==
                    PackageManager.PERMISSION_GRANTED
                ) {
                    request.grant(arrayOf(audio))
                } else {
                    pendingPermissionRequest = request
                    requestPermissions(
                        arrayOf(Manifest.permission.RECORD_AUDIO),
                        AUDIO_PERMISSION_REQUEST
                    )
                }
            }
        }

        webView = view
        setContentView(view)
        view.loadUrl("${baseUrl}/")
    }

    override fun onBackPressed() {
        val view = webView
        if (view?.canGoBack() == true) view.goBack()
        else super.onBackPressed()
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(
        requestCode: Int,
        resultCode: Int,
        data: Intent?
    ) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == FILE_CHOOSER_REQUEST) {
            val results = if (resultCode == RESULT_OK && data?.data != null) {
                arrayOf(data.data!!)
            } else null
            uploadCallback?.onReceiveValue(results)
            uploadCallback = null
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == AUDIO_PERMISSION_REQUEST) {
            val request = pendingPermissionRequest
            pendingPermissionRequest = null
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
                request?.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
            } else {
                request?.deny()
            }
        }
    }

    private fun statusOrToast(message: String) {
        if (::status.isInitialized && message.isNotBlank()) {
            status.text = "SPARKLE: $message"
        }
    }

    private fun safeError(exc: Exception): String =
        exc.message?.take(200)?.ifBlank { exc::class.java.simpleName }
            ?: exc::class.java.simpleName

    override fun onDestroy() {
        uploadCallback?.onReceiveValue(null)
        uploadCallback = null
        webView?.stopLoading()
        webView?.destroy()
        webView = null
        pendingPermissionRequest?.deny()
        pendingPermissionRequest = null
        executor.shutdownNow()
        super.onDestroy()
    }
}
