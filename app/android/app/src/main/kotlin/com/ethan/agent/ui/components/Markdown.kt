package com.ethan.agent.ui.components

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import dev.jeziellago.compose.markdowntext.MarkdownText

/**
 * Parsed token from a Markdown string.
 * Inline Markdown is rendered by [MarkdownText]; fenced code blocks are handled natively.
 */
private sealed interface MdToken {
    data class Text(val value: String) : MdToken
    data class FencedCode(val lang: String, val code: String) : MdToken
}

private val FENCE_RE = Regex("""```([a-zA-Z0-9_-]*)\n(.*?)```""", RegexOption.DOT_MATCHES_ALL)

private fun tokenize(text: String): List<MdToken> {
    val tokens = mutableListOf<MdToken>()
    var cursor = 0
    for (match in FENCE_RE.findAll(text)) {
        if (match.range.first > cursor) {
            tokens += MdToken.Text(text.substring(cursor, match.range.first))
        }
        tokens += MdToken.FencedCode(
            lang = match.groupValues[1].trim().lowercase(),
            code = match.groupValues[2].trimEnd(),
        )
        cursor = match.range.last + 1
    }
    if (cursor < text.length) {
        tokens += MdToken.Text(text.substring(cursor))
    }
    return tokens
}

@Composable
fun SimpleMarkdown(text: String, modifier: Modifier = Modifier) {
    val context = LocalContext.current

    // Track images in the text for lightbox
    val imageUrls = remember(text) {
        Regex("""!\[.*?]\((https?://[^)]+)\)""").findAll(text).map { it.groupValues[1] }.toList()
    }
    var lightboxIndex by remember { mutableStateOf<Int?>(null) }

    if (lightboxIndex != null && imageUrls.isNotEmpty()) {
        Lightbox(
            urls = imageUrls,
            initialIndex = lightboxIndex!!,
            onDismiss = { lightboxIndex = null },
        )
    }

    Column(modifier = modifier) {
        val tokens = remember(text) { tokenize(text) }

        tokens.forEach { token ->
            when (token) {
                is MdToken.Text -> {
                    if (token.value.isNotBlank()) {
                        MarkdownText(
                            markdown = token.value,
                            style = MaterialTheme.typography.bodyMedium.copy(
                                color = MaterialTheme.colorScheme.onSurface,
                            ),
                            onLinkClicked = { url ->
                                // Check if URL is an image — open lightbox
                                val imgIdx = imageUrls.indexOf(url)
                                if (imgIdx >= 0) {
                                    lightboxIndex = imgIdx
                                } else {
                                    runCatching {
                                        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                                    }
                                }
                            },
                        )
                        Spacer(Modifier.height(4.dp))
                    }
                }
                is MdToken.FencedCode -> {
                    if (token.lang == "mermaid") {
                        MermaidBlock(code = token.code, modifier = Modifier.padding(vertical = 4.dp))
                    } else {
                        CodeBlock(language = token.lang, code = token.code, modifier = Modifier.padding(vertical = 4.dp))
                    }
                    Spacer(Modifier.height(4.dp))
                }
            }
        }
    }
}
