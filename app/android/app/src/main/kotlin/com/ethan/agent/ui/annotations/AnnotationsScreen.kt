package com.ethan.agent.ui.annotations

import com.ethan.agent.shared.viewmodel.AnnotationsUiState
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.core.graphics.toColorInt
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.FormatQuote
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.Annotation
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AnnotationsScreen(
    state: AnnotationsUiState,
    onDelete: (Long) -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    Scaffold(
        topBar = { EthanTopBar(title = "标注") },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        when {
            state.isLoading -> LoadingBox(Modifier.padding(padding))
            state.groupedByMessage.isEmpty() -> Box(
                Modifier.fillMaxSize().padding(padding),
                contentAlignment = Alignment.Center,
            ) {
                Text("暂无标注", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            else -> AnnotationsList(
                grouped = state.groupedByMessage,
                onDelete = onDelete,
                modifier = Modifier.padding(padding),
            )
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun AnnotationsList(
    grouped: Map<String, List<Annotation>>,
    onDelete: (Long) -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier = modifier.fillMaxSize().padding(horizontal = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        grouped.forEach { (messageId, annotations) ->
            stickyHeader(key = "header_$messageId") {
                Surface(
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        "消息 #$messageId",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                    )
                }
            }
            items(annotations, key = { it.id }) { anno ->
                AnnotationCard(annotation = anno, onDelete = { onDelete(anno.id.toLong()) })
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalMaterial3Api::class)
@Composable
private fun AnnotationCard(annotation: Annotation, onDelete: () -> Unit) {
    var showConfirm by remember { mutableStateOf(false) }

    if (showConfirm) {
        AlertDialog(
            onDismissRequest = { showConfirm = false },
            title = { Text("删除标注") },
            text = { Text("确定要删除这条标注吗？") },
            confirmButton = { TextButton(onClick = { showConfirm = false; onDelete() }) { Text("删除") } },
            dismissButton = { TextButton(onClick = { showConfirm = false }) { Text("取消") } },
        )
    }

    Card(
        Modifier.fillMaxWidth().combinedClickable(
            onClick = {},
            onLongClick = { showConfirm = true },
        ),
    ) {
        Row(
            Modifier.padding(12.dp).fillMaxWidth(),
            verticalAlignment = Alignment.Top,
        ) {
            AnnotationTypeIcon(annotation.type, annotation.color, Modifier.padding(end = 8.dp, top = 2.dp))

            Column(Modifier.weight(1f)) {
                annotation.quote?.let { q ->
                    Text(
                        buildAnnotatedString {
                            withStyle(SpanStyle(textDecoration = annotationDecoration(annotation.type))) {
                                append(q)
                            }
                        },
                        style = MaterialTheme.typography.bodyMedium,
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                annotation.note?.let { note ->
                    Text(
                        note,
                        style = MaterialTheme.typography.bodySmall.copy(fontStyle = FontStyle.Italic),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }

            IconButton(onClick = { showConfirm = true }, modifier = Modifier.size(32.dp)) {
                Icon(Icons.Default.Delete, contentDescription = "删除", modifier = Modifier.size(18.dp))
            }
        }
    }
}

@Composable
private fun AnnotationTypeIcon(type: String, colorHex: String?, modifier: Modifier = Modifier) {
    val tint = colorHex?.let { parseColor(it) } ?: annotationDefaultColor(type)
    Icon(Icons.Default.FormatQuote, contentDescription = type, tint = tint, modifier = modifier.size(20.dp))
}

private fun annotationDefaultColor(type: String) = when (type) {
    "highlight" -> Color(0xFFFFF176)
    "underline" -> Color(0xFF42A5F5)
    "strike" -> Color(0xFFEF5350)
    "comment" -> Color(0xFF66BB6A)
    else -> Color.Gray
}

private fun annotationDecoration(type: String) = when (type) {
    "underline" -> TextDecoration.Underline
    "strike" -> TextDecoration.LineThrough
    else -> TextDecoration.None
}

private fun parseColor(hex: String): Color? = runCatching {
    Color(hex.toColorInt())
}.getOrNull()

/**
 * Standalone composable that renders annotation effects over a message text.
 * Accepts a raw content string and a list of annotations; returns an AnnotatedString
 * with highlight/underline/strikethrough spans applied. Call from ChatScreen or
 * any message-rendering composable.
 */
@Suppress("unused")
@Composable
fun AnnotationLayer(
    content: String,
    annotations: List<Annotation>,
    modifier: Modifier = Modifier,
) {
    val annotated = remember(content, annotations) {
        buildAnnotatedString {
            append(content)
            annotations.forEach { anno ->
                val start = anno.start.coerceIn(0, content.length)
                val end = anno.end.coerceIn(start, content.length)
                if (start >= end) return@forEach
                val color = anno.color?.let { parseColor(it) } ?: annotationDefaultColor(anno.type)
                addStyle(
                    style = SpanStyle(
                        background = if (anno.type == "highlight") color.copy(alpha = 0.4f) else Color.Unspecified,
                        textDecoration = annotationDecoration(anno.type),
                        color = if (anno.type == "highlight") Color.Unspecified else color,
                    ),
                    start = start,
                    end = end,
                )
            }
        }
    }
    Text(text = annotated, modifier = modifier)
}
