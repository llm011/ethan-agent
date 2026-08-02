package com.ethan.agent.ui.components

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.isSpecified
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.jeziellago.compose.markdowntext.MarkdownText

/**
 * Parsed token from a Markdown string.
 * Inline Markdown is rendered by [MarkdownText]; fenced code blocks are handled natively.
 */
private sealed interface MdToken {
    data class Text(val value: String) : MdToken
    data class FencedCode(val lang: String, val code: String) : MdToken
    data class Table(val headers: List<String>, val rows: List<List<String>>) : MdToken
}

private val FENCE_RE = Regex("""```([a-zA-Z0-9_-]*)\n(.*?)```""", RegexOption.DOT_MATCHES_ALL)

/** Parse a pipe-delimited row into trimmed cell values */
private fun parseTableRow(line: String): List<String> =
    line.trim().removePrefix("|").removeSuffix("|").split("|").map { it.trim() }

/** Check if a line is a table separator (e.g. |---|---|) */
private fun isSeparatorLine(line: String): Boolean =
    line.trim().removePrefix("|").removeSuffix("|").split("|").all { it.trim().matches(Regex(""":?-{1,}:?""")) }

/**
 * Second pass: extract markdown tables from a Text token.
 * A table = header row + separator row + 1..N data rows, all lines starting with |.
 */
private fun extractTables(text: String): List<MdToken> {
    val lines = text.lines()
    val result = mutableListOf<MdToken>()
    val buffer = StringBuilder()
    var i = 0

    while (i < lines.size) {
        val line = lines[i]
        // Detect potential table start: line starts with | and next line is separator
        if (line.trimStart().startsWith("|") && i + 1 < lines.size && isSeparatorLine(lines[i + 1])) {
            // Flush accumulated text
            if (buffer.isNotEmpty()) {
                result += MdToken.Text(buffer.toString())
                buffer.clear()
            }
            // Parse header
            val headers = parseTableRow(line)
            i += 2 // skip header + separator
            // Parse data rows
            val rows = mutableListOf<List<String>>()
            while (i < lines.size && lines[i].trimStart().startsWith("|")) {
                rows += parseTableRow(lines[i])
                i++
            }
            result += MdToken.Table(headers = headers, rows = rows)
        } else {
            buffer.appendLine(line)
            i++
        }
    }
    if (buffer.isNotEmpty()) {
        // Remove trailing newline added by appendLine
        val remaining = buffer.toString().removeSuffix("\n")
        if (remaining.isNotEmpty()) result += MdToken.Text(remaining)
    }
    return result
}

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
    // Second pass: extract tables from Text tokens
    return tokens.flatMap { token ->
        if (token is MdToken.Text) extractTables(token.value) else listOf(token)
    }
}

@Composable
fun SimpleMarkdown(
    text: String,
    modifier: Modifier = Modifier,
    textColor: Color = Color.Unspecified,
) {
    val context = LocalContext.current
    val defaultColor = MaterialTheme.colorScheme.onSurface
    val resolvedTextColor = if (textColor.isSpecified) textColor else defaultColor

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
                                color = resolvedTextColor,
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
                is MdToken.Table -> {
                    MarkdownTable(
                        headers = token.headers,
                        rows = token.rows,
                        modifier = Modifier.padding(vertical = 4.dp),
                        textColor = resolvedTextColor,
                    )
                    Spacer(Modifier.height(4.dp))
                }
            }
        }
    }
}

@Composable
private fun MarkdownTable(
    headers: List<String>,
    rows: List<List<String>>,
    modifier: Modifier = Modifier,
    textColor: Color = Color.Unspecified,
) {
    val borderColor = MaterialTheme.colorScheme.outlineVariant
    val headerBg = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
    val resolvedColor = if (textColor.isSpecified) textColor else MaterialTheme.colorScheme.onSurface
    val textStyle = MaterialTheme.typography.bodySmall.copy(
        color = resolvedColor,
    )
    val headerStyle = textStyle.copy(fontWeight = FontWeight.SemiBold)

    Box(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .border(1.dp, borderColor, RoundedCornerShape(8.dp))
            .horizontalScroll(rememberScrollState()),
    ) {
        Column {
            // Header row
            Row(modifier = Modifier.background(headerBg).width(IntrinsicSize.Max)) {
                headers.forEach { cell ->
                    Box(
                        modifier = Modifier
                            .padding(horizontal = 12.dp, vertical = 8.dp)
                            .width(IntrinsicSize.Max),
                        contentAlignment = Alignment.CenterStart,
                    ) {
                        Text(
                            text = cell,
                            style = headerStyle,
                            maxLines = 1,
                            overflow = TextOverflow.Visible,
                            softWrap = false,
                        )
                    }
                }
            }
            // Data rows
            rows.forEach { row ->
                Row(modifier = Modifier.width(IntrinsicSize.Max)) {
                    row.forEach { cell ->
                        Box(
                            modifier = Modifier
                                .padding(horizontal = 12.dp, vertical = 6.dp)
                                .width(IntrinsicSize.Max),
                            contentAlignment = Alignment.CenterStart,
                        ) {
                            Text(
                                text = cell,
                                style = textStyle,
                                maxLines = 1,
                                overflow = TextOverflow.Visible,
                                softWrap = false,
                            )
                        }
                    }
                }
            }
        }
    }
}
