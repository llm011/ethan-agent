package com.ethan.agent.ui.components

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AudioFile
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.InsertDriveFile
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.VideoFile
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.ethan.agent.core.model.FileCard
import com.ethan.agent.core.model.FileSignature

private val IMAGE_KINDS = setOf("png", "jpg", "jpeg", "gif", "webp", "svg", "bmp")
private val AUDIO_KINDS = setOf("mp3", "m4a", "wav", "ogg", "flac")
private val VIDEO_KINDS = setOf("mp4", "mov", "avi", "mkv", "webm")

@Composable
fun FileCardView(
    card: FileCard,
    serverUrl: String,
    sessionId: String?,
    signFile: (suspend (String) -> FileSignature?)? = null,
) {
    val context = LocalContext.current
    // 渲染时换 path 级签名（?user=&sig=，10 分钟有效）：AsyncImage 与系统浏览器都带
    // 不上 Authorization header / cookie，签名 URL 是唯一可行的鉴权通道（deps.py 三通道）
    var signature by remember(card.path) { mutableStateOf<FileSignature?>(null) }
    LaunchedEffect(card.path) { signature = signFile?.invoke(card.path) }

    fun buildViewUrl(): String {
        val base = "${serverUrl.trimEnd('/')}/api/files/view?path=${Uri.encode(card.path)}"
        val sid = if (sessionId != null) "&session_id=${Uri.encode(sessionId)}" else ""
        val sig = signature?.let { "&user=${Uri.encode(it.user)}&sig=${Uri.encode(it.sig)}" } ?: ""
        return "$base$sid$sig"
    }

    fun buildDownloadUrl(): String {
        val base = "${serverUrl.trimEnd('/')}/api/files/download?path=${Uri.encode(card.path)}"
        val sid = if (sessionId != null) "&session_id=${Uri.encode(sessionId)}" else ""
        val sig = signature?.let { "&user=${Uri.encode(it.user)}&sig=${Uri.encode(it.sig)}" } ?: ""
        return "$base$sid$sig"
    }

    fun openInBrowser(url: String) {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        context.startActivity(intent)
    }

    when {
        IMAGE_KINDS.contains(card.kind) -> ImageFileCardView(
            card = card,
            viewUrl = buildViewUrl(),
        )
        AUDIO_KINDS.contains(card.kind) -> AudioFileCardView(
            card = card,
            onPlay = { openInBrowser(buildViewUrl()) },
            onDownload = { openInBrowser(buildDownloadUrl()) },
        )
        VIDEO_KINDS.contains(card.kind) -> VideoFileCardView(
            card = card,
            onPlay = { openInBrowser(buildViewUrl()) },
            onDownload = { openInBrowser(buildDownloadUrl()) },
        )
        else -> GenericFileCardView(
            card = card,
            onDownload = { openInBrowser(buildDownloadUrl()) },
        )
    }
}

@Composable
private fun ImageFileCardView(card: FileCard, viewUrl: String) {
    var showLightbox by remember { mutableStateOf(false) }

    Column {
        Surface(
            modifier = Modifier
                .sizeIn(maxWidth = 240.dp, maxHeight = 180.dp)
                .clip(RoundedCornerShape(8.dp))
                .clickable { showLightbox = true },
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f),
        ) {
            AsyncImage(
                model = viewUrl,
                contentDescription = card.title ?: card.filename,
                contentScale = ContentScale.Fit,
                modifier = Modifier.sizeIn(maxWidth = 240.dp, maxHeight = 180.dp),
            )
        }
        Text(
            text = card.title ?: card.filename,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 2.dp),
        )
    }

    if (showLightbox) {
        Lightbox(
            urls = listOf(viewUrl),
            initialIndex = 0,
            onDismiss = { showLightbox = false },
        )
    }
}

@Composable
private fun AudioFileCardView(card: FileCard, onPlay: () -> Unit, onDownload: () -> Unit) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        modifier = Modifier.fillMaxWidth().sizeIn(maxWidth = 300.dp),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(
                Icons.Default.AudioFile,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(32.dp),
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = card.title ?: card.filename,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = buildString {
                        append(card.kind.uppercase())
                        card.sizeKb?.let { append(" · ${formatSize(it)}") }
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onPlay, modifier = Modifier.size(36.dp)) {
                Icon(
                    Icons.Default.PlayCircle,
                    contentDescription = "播放",
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(28.dp),
                )
            }
            IconButton(onClick = onDownload, modifier = Modifier.size(36.dp)) {
                Icon(
                    Icons.Default.Download,
                    contentDescription = "下载",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}

@Composable
private fun VideoFileCardView(card: FileCard, onPlay: () -> Unit, onDownload: () -> Unit) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        modifier = Modifier.fillMaxWidth().sizeIn(maxWidth = 300.dp),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(
                Icons.Default.VideoFile,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(32.dp),
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = card.title ?: card.filename,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = buildString {
                        append(card.kind.uppercase())
                        card.sizeKb?.let { append(" · ${formatSize(it)}") }
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onPlay, modifier = Modifier.size(36.dp)) {
                Icon(
                    Icons.Default.PlayCircle,
                    contentDescription = "播放",
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(28.dp),
                )
            }
            IconButton(onClick = onDownload, modifier = Modifier.size(36.dp)) {
                Icon(
                    Icons.Default.Download,
                    contentDescription = "下载",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}

@Composable
private fun GenericFileCardView(card: FileCard, onDownload: () -> Unit) {
    Surface(
        onClick = onDownload,
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        modifier = Modifier.fillMaxWidth().sizeIn(maxWidth = 300.dp),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(
                Icons.Default.InsertDriveFile,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(32.dp),
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = card.title ?: card.filename,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = buildString {
                        append(card.kind.uppercase())
                        card.sizeKb?.let { append(" · ${formatSize(it)}") }
                        card.pageCount?.let { append(" · ${it} 页") }
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Icon(
                Icons.Default.Download,
                contentDescription = "下载",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

private fun formatSize(kb: Float): String {
    return if (kb >= 1024) "${String.format("%.1f", kb / 1024)} MB" else "${kb.toInt()} KB"
}
