package com.ethan.agent.core.model

object ServerUrlUtils {
    const val DEFAULT_SERVER_URL = "http://127.0.0.1:8900"

    /**
     * Normalize user input to origin only: scheme + host + port.
     * Strips paths like /chat/, /api/ and fixes pasted URLs appended to defaults.
     *
     * Pure-Kotlin (KMP-safe) origin parser — replaces java.net.URI so this runs
     * unchanged on Android, iOS and any other Kotlin target.
     */
    fun normalize(raw: String): String? {
        var s = raw.trim()
        if (s.isBlank()) return null

        s = fixDoubleScheme(s)

        if (!s.contains("://")) {
            s = "https://$s"
        }

        return parseOrigin(s)
    }

    /**
     * Extract scheme://host[:port] from a URL string. Returns null for anything
     * that isn't a well-formed http/https authority.
     */
    private fun parseOrigin(input: String): String? {
        val schemeSep = input.indexOf("://")
        if (schemeSep <= 0) return null
        val scheme = input.substring(0, schemeSep).lowercase()
        if (scheme != "http" && scheme != "https") return null

        // authority = everything after :// up to the first '/', '?' or '#'
        val rest = input.substring(schemeSep + 3)
        val authorityEnd = rest.indexOfFirst { it == '/' || it == '?' || it == '#' }
        val authority = if (authorityEnd >= 0) rest.substring(0, authorityEnd) else rest
        if (authority.isBlank()) return null

        // strip userinfo (user:pass@) if present
        val hostPort = authority.substringAfterLast('@')

        // split host / port — guard against IPv6 [::1] form
        val host: String
        val port: Int
        if (hostPort.startsWith("[")) {
            val close = hostPort.indexOf(']')
            if (close < 0) return null
            host = hostPort.substring(0, close + 1)
            val after = hostPort.substring(close + 1)
            port = if (after.startsWith(":")) after.drop(1).toIntOrNull() ?: return null else -1
        } else {
            val colon = hostPort.lastIndexOf(':')
            if (colon >= 0) {
                host = hostPort.substring(0, colon)
                port = hostPort.substring(colon + 1).toIntOrNull() ?: return null
            } else {
                host = hostPort
                port = -1
            }
        }
        if (host.isBlank()) return null

        val portSuffix = if (port > 0) ":$port" else ""
        return "$scheme://$host$portSuffix"
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
