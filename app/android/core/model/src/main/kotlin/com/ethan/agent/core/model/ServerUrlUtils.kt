package com.ethan.agent.core.model

import java.net.URI

object ServerUrlUtils {
    const val DEFAULT_SERVER_URL = "http://127.0.0.1:8900"

    /**
     * Normalize user input to origin only: scheme + host + port.
     * Strips paths like /chat/, /api/ and fixes pasted URLs appended to defaults.
     */
    fun normalize(raw: String): String? {
        var s = raw.trim()
        if (s.isBlank()) return null

        s = fixDoubleScheme(s)

        if (!s.contains("://")) {
            s = "https://$s"
        }

        val withPath = if (s.contains("://") && !s.substringAfter("://").contains("/")) {
            "$s/"
        } else {
            s
        }

        return try {
            val uri = URI(withPath)
            val scheme = uri.scheme?.lowercase() ?: return null
            if (scheme !in setOf("http", "https")) return null
            val host = uri.host ?: return null
            val port = uri.port
            val portSuffix = when {
                port > 0 -> ":$port"
                scheme == "https" -> ""
                else -> ""
            }
            "$scheme://$host$portSuffix"
        } catch (_: Exception) {
            null
        }
    }

    /** e.g. "http://127.0.0.1:8900https://chat.example.com:29999" → "https://chat.example.com:29999" */
    private fun fixDoubleScheme(input: String): String {
        val httpsIdx = input.lastIndexOf("https://")
        val httpIdx = input.lastIndexOf("http://")
        val idx = maxOf(httpsIdx, httpIdx)
        return if (idx > 0) input.substring(idx) else input
    }

    fun toApiBaseUrl(serverUrl: String, fallback: String = DEFAULT_SERVER_URL): String {
        val origin = normalize(serverUrl) ?: normalize(fallback) ?: fallback
        return "${origin.trimEnd('/')}/api"
    }

    fun toRetrofitBaseUrl(apiBaseUrl: String): String {
        val base = apiBaseUrl.trimEnd('/')
        return if (base.endsWith("/api")) "$base/" else "$base/api/"
    }
}
