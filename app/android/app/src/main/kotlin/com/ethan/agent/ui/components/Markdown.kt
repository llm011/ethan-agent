package com.ethan.agent.ui.components

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.text.ClickableText
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
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
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
    /**
     * ATX 标题（# .. ######）。自己渲染而不是交给库 —— 库的标题是按基础字号等比
     * 放大的，H1 会大得离谱；这里用 MaterialTheme 的 title/headline 档位，和 App
     * 其它页面同一把尺子。
     */
    data class Heading(val level: Int, val value: String) : MdToken
}

private val FENCE_RE = Regex("""```([a-zA-Z0-9_-]*)\n(.*?)```""", RegexOption.DOT_MATCHES_ALL)

/** Parse a pipe-delimited row into trimmed cell values */
private fun parseTableRow(line: String): List<String> =
    line.trim().removePrefix("|").removeSuffix("|").split("|").map { it.trim() }

/** Check if a line is a table separator (e.g. |---|---|) */
private fun isSeparatorLine(line: String): Boolean =
    line.trim().removePrefix("|").removeSuffix("|").split("|").all { it.trim().matches(Regex(""":?-{1,}:?""")) }

private val HEADING_RE = Regex("""^(#{1,6})\\s+(.*)$""")

/*
 * Second pass: pull `# 标题` 行出来。标题行必须独占一行，且不在代码块里
 * （调用点在 tokenize 的第二遍，Text token 已经和围栏代码块分开了）。
 */
private fun extractHeadings(text: String): List<MdToken> {
    val out = mutableListOf<MdToken>()
    val buffer = StringBuilder()
    fun flush() {
        val v = buffer.toString().removeSuffix("\n")
        if (v.isNotBlank()) out += MdToken.Text(v)
        buffer.clear()
    }
    text.lines().forEach { line ->
        val m = HEADING_RE.matchEntire(line.trim())
        if (m != null) {
            flush()
            out += MdToken.Heading(m.groupValues[1].length, m.groupValues[2].trim())
        } else {
            buffer.appendLine(line)
        }
    }
    flush()
    return out
}

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

// 是否是「站内文档相对链接」——形如 ./architecture.md、../docs/x.md#anchor。
// 判据：没有 scheme（不是 http: / mailto: 等）且以 .md 结尾（可带 # 锚点）。
// 纯锚点链接（#section）不算——那是页内跳转，本库不处理，也不该当成另一篇文档。
private fun isRelativeDocLink(url: String): Boolean {
    val u = url.trim()
    if (u.isEmpty() || u.startsWith("#")) return false
    if (u.contains("://") || u.startsWith("mailto:") || u.startsWith("tel:")) return false
    return u.substringBefore('#').endsWith(".md", ignoreCase = true)
}

// 把相对文档链接归一成 slug（后端 /api/docs/{slug} 的键就是去掉目录和 .md 的文件名）。
//   ./architecture.md      -> architecture
//   ../docs/knowledge.md#x -> knowledge
//   architecture.md        -> architecture
private fun normalizeDocLink(url: String): String =
    url.trim()
        .substringBefore('#')          // 丢掉锚点
        .substringAfterLast('/')       // 丢掉 ./ ../ docs/ 等目录部分
        .removeSuffix(".md")
        .removeSuffix(".MD")

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
    // Second pass: tables, then headings, both only inside Text tokens.
    return tokens
        .flatMap { token -> if (token is MdToken.Text) extractTables(token.value) else listOf(token) }
        .flatMap { token -> if (token is MdToken.Text) extractHeadings(token.value) else listOf(token) }
}

/** `<!-- ... -->`：Web 渲染前会整段剥掉（docs-view.tsx），这里保持一致。 */
private val HTML_COMMENT_RE = Regex("""<!--[\s\S]*?-->""")

/** `![alt](src)` —— 只关心 src。 */
private val IMAGE_RE = Regex("""(!\[[^\]]*]\()([^)]+)(\))""")

/**
 * 渲染前的规范化，对齐 Web 的 `docs-view.tsx`：
 *
 * 1. **剥掉 HTML 注释**。文档正文里的图源用 `<!-- diagram-source ... -->` 包着。
 *    Web 在渲染前 `replace(/<!--[\s\S]*?-->/g, "")` 掉了，App 之前照单全收 ——
 *    用户看到的就是「Web 上不展示的内容，App 上冒出来了」。
 *
 * 2. **把相对图片路径补成绝对 URL**。正文写的是 `./images/agent-loop-flow.jpg`，
 *    相对路径没法直接加载（和相对 `.md` 链接同一个病根）。Web 用
 *    `resolveDocsImageUrl()` 拼成 `${API_URL}/docs/images/<file>`，这里做同样的事。
 *
 * @param apiBase 后端 API 根地址（形如 `http://host:port/api`）；为 null 时只剥注释。
 */
private fun preprocessDocMarkdown(text: String, apiBase: String?): String {
    val stripped = HTML_COMMENT_RE.replace(text, "")
    if (apiBase.isNullOrBlank()) return stripped
    return IMAGE_RE.replace(stripped) { m ->
        val src = m.groupValues[2].trim()
        val resolved = when {
            src.startsWith("./images/") -> apiBase + "/docs/images/" + src.removePrefix("./images/")
            src.startsWith("images/") -> apiBase + "/docs/images/" + src.removePrefix("images/")
            else -> src
        }
        m.groupValues[1] + resolved + m.groupValues[3]
    }
}

/**
 * 渲染 Markdown 文本。
 *
 * onDocLink：站内相对链接（形如 `./architecture.md`、`../docs/x.md#y`）的处理器。
 * 文档页的正文大量使用相对路径互相引用（docs 目录里 19 处），而相对路径不是
 * 合法 URI —— 直接丢给 `ACTION_VIEW` 会被系统拒绝、异常又被 runCatching 吞掉，
 * 用户看到的就是「链接点不动」。传了这个回调就把 .md 相对链接转成站内跳转
 * （由调用方用 slug 打开对应文档）。
 */
@Composable
fun SimpleMarkdown(
    text: String,
    modifier: Modifier = Modifier,
    textColor: Color = Color.Unspecified,
    linkColor: Color = MaterialTheme.colorScheme.primary,
    onDocLink: ((String) -> Unit)? = null,
    apiBase: String? = null,
    /**
     * 阅读模式用：正文行高放宽（对齐 Web reading-mode 的 `leading-7` ≈ 1.75×）。
     * 聊天气泡里保持默认紧凑行高——气泡本来就窄，行距再大就撑爆了。
     */
    relaxedLeading: Boolean = false,
) {
    val context = LocalContext.current
    val defaultColor = MaterialTheme.colorScheme.onSurface
    val resolvedTextColor = if (textColor.isSpecified) textColor else defaultColor

    // 正文基准字号与行高（阅读模式放宽，气泡内保持紧凑）
    val baseBody = MaterialTheme.typography.bodyMedium
    val bodyTextStyle = remember(relaxedLeading, resolvedTextColor, baseBody) {
        if (relaxedLeading) {
            baseBody.copy(
                color = resolvedTextColor,
                lineHeight = baseBody.fontSize * 1.75f,
                fontSize = baseBody.fontSize * 1.07f,
            )
        } else {
            baseBody.copy(color = resolvedTextColor)
        }
    }

    // 先归一化：剥掉 HTML 注释、把相对图片路径补成绝对 URL（见 preprocessDocMarkdown）。
    val normalized = remember(text, apiBase) { preprocessDocMarkdown(text, apiBase) }

    // Track images in the text for lightbox
    val imageUrls = remember(normalized) {
        Regex("""!\[.*?]\((https?://[^)]+)\)""")
            .findAll(normalized).map { it.groupValues[1] }.toList()
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
        val tokens = remember(normalized) { tokenize(normalized) }

        tokens.forEach { token ->
            when (token) {
                is MdToken.Text -> {
                    if (token.value.isNotBlank()) {
                        MarkdownText(
                            markdown = token.value,
                            style = bodyTextStyle,
                            onLinkClicked = { url ->
                                // Check if URL is an image — open lightbox
                                val imgIdx = imageUrls.indexOf(url)
                                when {
                                    imgIdx >= 0 -> lightboxIndex = imgIdx
                                    // 站内相对链接（./a.md、../x/y.md）当作跳转到另一篇文档：交给
                                    // onDocLink，由调用方按 slug 打开。不这么做的话
                                    // ACTION_VIEW 会拒绝相对路径，表现为「点了没反应」。
                                    onDocLink != null && isRelativeDocLink(url) ->
                                        onDocLink(normalizeDocLink(url))
                                    else -> runCatching {
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
                is MdToken.Heading -> {
                    val style = when (token.level) {
                        1 -> MaterialTheme.typography.headlineSmall
                        2 -> MaterialTheme.typography.titleLarge
                        3 -> MaterialTheme.typography.titleMedium
                        else -> MaterialTheme.typography.titleSmall
                    }
                    Text(
                        text = token.value,
                        style = style.copy(
                            color = resolvedTextColor,
                            fontWeight = FontWeight.SemiBold,
                        ),
                        modifier = Modifier.padding(top = 12.dp, bottom = 4.dp),
                    )
                }
                is MdToken.Table -> {
                    MarkdownTable(
                        headers = token.headers,
                        rows = token.rows,
                        modifier = Modifier.padding(vertical = 4.dp),
                        textColor = resolvedTextColor,
                        linkColor = linkColor,
                        onLinkClicked = { url ->
                            if (onDocLink != null && isRelativeDocLink(url)) {
                                onDocLink(normalizeDocLink(url))
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
        }
    }
}

// ── 表格单元格的富文本 ────────────────────────────────────────────────────
// 表格是自己解析的（见 extractTables），所以单元格里仍是**原始 markdown 文本**。
// compose-markdown 只处理 Text token，管不到我们手搓的表格 —— 结果就是用户
// 截图里看到的 `[架构总览](./architecture.md)` 原样露出来。把 `[label](url)`
// 和 `` `code` `` 在渲染前拆成 annotated string。

private val INLINE_LINK_RE = Regex("""\[([^\]]*)]\(([^)]+)\)""")
private val INLINE_CODE_RE = Regex("""`([^`]+)`""")

/** 一次扫描里收集到的一段替换：覆盖 [start, end)，用 replacement 替换。 */
private class SpanMatch(val start: Int, val end: Int, val replacement: String)

/**
 * 把单元格文本转成 [AnnotatedString]：
 * - `[label](url)` → 只显示 label，标上 url 的 annotation（点击时再分发）
 * - `` `code` `` → 去掉反引号，用等宽字体 + 淡背景
 * 两种语法混在一起时按位置取不重叠的匹配（先来先得）。
 */
private fun buildTableCell(text: String, linkColor: Color): AnnotatedString {
    val spans = mutableListOf<SpanMatch>()
    val taken = mutableListOf<IntRange>()

    fun claim(range: IntRange): Boolean {
        if (taken.any { it.first <= range.last && range.first <= it.last }) return false
        taken += range
        return true
    }

    INLINE_LINK_RE.findAll(text).forEach { m ->
        if (claim(m.range)) {
            spans += SpanMatch(m.range.first, m.range.last + 1, m.groupValues[1])
        }
    }
    INLINE_CODE_RE.findAll(text).forEach { m ->
        if (claim(m.range)) {
            spans += SpanMatch(m.range.first, m.range.last + 1, m.groupValues[1])
        }
    }
    spans.sortBy { it.start }

    return buildAnnotatedString {
        var cursor = 0
        spans.forEach { s ->
            if (s.start > cursor) append(text.substring(cursor, s.start))
            val code = INLINE_CODE_RE.matches(text.substring(s.start, s.end))
            withStyle(
                if (code) {
                    SpanStyle(fontFamily = FontFamily.Monospace, background = Color(0x14000000))
                } else {
                    SpanStyle(color = linkColor)
                },
            ) {
                append(s.replacement)
            }
            // 链接：把 url 记在这段文字上，点击时由 onLinkClicked 取回。
            if (!code) {
                val url = INLINE_LINK_RE.matchEntire(text.substring(s.start, s.end))?.groupValues?.get(2)
                if (url != null) addStringAnnotation(LINK_TAG, url, s.start, s.end)
            }
            cursor = s.end
        }
        if (cursor < text.length) append(text.substring(cursor))
    }
}

/** 表格单元格里 link 文字的 annotation tag —— 与 Text token 用的 tag 区分开。 */
private const val LINK_TAG = "ethan:md-link"

@Composable
private fun MarkdownTable(
    headers: List<String>,
    rows: List<List<String>>,
    modifier: Modifier = Modifier,
    textColor: Color = Color.Unspecified,
    linkColor: Color = MaterialTheme.colorScheme.primary,
    onLinkClicked: (String) -> Unit = {},
) {
    val borderColor = MaterialTheme.colorScheme.outlineVariant
    val headerBg = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
    val resolvedColor = if (textColor.isSpecified) textColor else MaterialTheme.colorScheme.onSurface
    val textStyle = MaterialTheme.typography.bodySmall.copy(
        color = resolvedColor,
    )
    val headerStyle = textStyle.copy(fontWeight = FontWeight.SemiBold)
    // 表格单元格里的链接颜色 —— primary，配合下划线，一眼能看出是能点的。
    val cells = remember(headers, rows, linkColor) {
        val h = headers.map { buildTableCell(it, linkColor) }
        val r = rows.map { row -> row.map { buildTableCell(it, linkColor) } }
        h to r
    }

    Box(
        modifier = modifier
            .clip(MaterialTheme.shapes.small)
            .border(1.dp, borderColor, MaterialTheme.shapes.small)
            .horizontalScroll(rememberScrollState()),
    ) {
        Column {
            // Header row
            Row(modifier = Modifier.background(headerBg).width(IntrinsicSize.Max)) {
                cells.first.forEach { cell ->
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
            cells.second.forEach { row ->
                Row(modifier = Modifier.width(IntrinsicSize.Max)) {
                    row.forEach { cell ->
                        Box(
                            modifier = Modifier
                                .padding(horizontal = 12.dp, vertical = 6.dp)
                                .width(IntrinsicSize.Max),
                            contentAlignment = Alignment.CenterStart,
                        ) {
                            ClickableText(
                                text = cell,
                                style = textStyle,
                                maxLines = 1,
                                overflow = TextOverflow.Visible,
                                softWrap = false,
                                onClick = { offset ->
                                    cell.getStringAnnotations(LINK_TAG, offset, offset)
                                        .firstOrNull()
                                        ?.let { onLinkClicked(it.item) }
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}
