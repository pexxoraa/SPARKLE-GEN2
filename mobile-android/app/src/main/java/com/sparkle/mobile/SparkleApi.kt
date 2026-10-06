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

                // Personal Core requires Content-Length. Do not allow
                // HttpURLConnection to switch this request to chunked
                // transfer encoding.
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
        // Pairing codes are displayed/copy-pasted by humans. Normalize common
        // Unicode dash variants and whitespace before sending to the Core.
        // The Core canonicalizes with trim()+uppercase(), so this keeps the
        // Android client compatible without changing the server contract.
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
                JSONArray(
                    listOf(
                        "conversation",
                        "notifications",
                        "approvals",
                        "task_status",
                        "device_management",
                        "artifacts",
                    )
                ),
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

    fun validateCredentials(token: String): Boolean {
        return try {
            request("GET", "/api/sessions", token = token)
            true
        } catch (exc: SparkleApiException) {
            if (exc.statusCode == 401 || exc.statusCode == 403) false else throw exc
        }
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
