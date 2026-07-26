package com.ethan.agent.ui.components

import android.annotation.SuppressLint
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView

// Minimal mermaid HTML template. Loads mermaid from CDN; falls back gracefully offline.
private fun mermaidHtml(diagramCode: String, darkMode: Boolean): String {
    val theme = if (darkMode) "dark" else "neutral"
    val bg = if (darkMode) "#1C1B1F" else "#FFFBFE"
    val escaped = diagramCode
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    return """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { margin:0; background:$bg; }
  .mermaid { display:flex; justify-content:center; }
  svg { max-width:100%; height:auto; }
</style>
</head>
<body>
<div class="mermaid">$escaped</div>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
  mermaid.initialize({ startOnLoad:true, theme:'$theme', securityLevel:'loose' });
</script>
</body>
</html>
    """.trimIndent()
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun MermaidBlock(code: String, modifier: Modifier = Modifier) {
    val darkMode = isSystemInDarkTheme()
    val html = remember(code, darkMode) { mermaidHtml(code, darkMode) }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = 80.dp, max = 400.dp)
            .background(if (darkMode) Color(0xFF1C1B1F) else Color(0xFFFFFBFE)),
    ) {
        AndroidView(
            factory = { ctx ->
                WebView(ctx).apply {
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    setBackgroundColor(android.graphics.Color.TRANSPARENT)
                    webViewClient = WebViewClient()
                }
            },
            update = { webView ->
                webView.loadDataWithBaseURL(
                    "https://cdn.jsdelivr.net",
                    html,
                    "text/html",
                    "UTF-8",
                    null,
                )
            },
        )
    }
}
