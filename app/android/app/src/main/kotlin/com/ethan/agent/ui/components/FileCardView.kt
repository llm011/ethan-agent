package com.ethan.agent.ui.components

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AudioFile
import androidx.compose.material.icons.filled.BrokenImage
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.InsertDriveFile
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.VideoFile
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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
import com.ethan.agent.core.model.FileSignatureFreshness
import kotlinx.coroutines.launch

private val IMAGE_KINDS = setOf("png", "jpg", "jpeg", "gif", "webp", "svg", "bmp")
private val AUDIO_KINDS = setOf("mp3", "m4a", "wav", "ogg", "flac")
private val VIDEO_KINDS = setOf("mp4", "mov", "avi", "mkv", "webm")

/**
 * 交付文件卡片（深度听书交付的 MP3、PPT、视频等都走这里）。
 *
 * 签名状态机是这张卡片的核心：服务端只认「会话授权 + 10 分钟短期签名」的 URL，
 * 而签名必须在渲染后异步取。历史实现的两个坑：
 *   1) 签名还没回来（或签名失败）时点「播放/下载」，拼出的是没有 user/sig 的直链，
 *      系统浏览器只会打开一个 401 错误页——用户看到一串 JSON，App 里没有任何提示；
 *   2) 签名签一次就存着，页面停留超过 10 分钟后播放/下载必然 401，同样静默失败。
 * 现在：点击时按 TTL 判断签名是否还要得及，过期就换新；盖章失败给明确错误 + 重试；
 * 音频播放交给应用内播放器（不再把 MP3 丢给外部浏览器，那在安卓上通常变成下载）。
 */
@Composable
fun FileCardView(
    card: FileCard,
    serverUrl: String,
    sessionId: String?,
    signFile: (suspend (String) -> FileSignature?)? = null,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var signature by remember(card.path) { mutableStateOf<FileSignature?>(null) }
    var signedAtMs by remember(card.path) { mutableLongStateOf(0L) }
    var signing by remember(card.path) { mutableStateOf(false) }
    var error by remember(card.path) { mutableStateOf<String?>(null) }
    // 用户点了「播放/下载」之后、真正打开之前的等待（换签 + 启动外部应用）
    var actionPending by remember(card.path) { mutableStateOf(false) }
    // 非空 = 打开应用内音频播放器
    var playingUrl by remember(card.path) { mutableStateOf<String?>(null) }

    fun signedUrl(kind: String, sig: FileSignature): String {
        val base = "${serverUrl.trimEnd('/')}/api/files/$kind?path=${Uri.encode(card.path)}"
        val sid = if (sessionId != null) "&session_id=${Uri.encode(sessionId)}" else ""
        return "$base$sid&user=${Uri.encode(sig.user)}&sig=${Uri.encode(sig.sig)}"
    }

    suspend fun refreshSignature(): FileSignature? {
        val signer = signFile
        if (signer == null) {
            error = "当前会话没有文件授权，无法打开交付文件"
            return null
        }
        signing = true
        val fresh = try {
            signer(card.path)
        } catch (_: Exception) {
            null
        }
        signing = false
        if (fresh == null) {
            error = "文件授权获取失败，请检查网络后重试"
            return null
        }
        signature = fresh
        signedAtMs = System.currentTimeMillis()
        error = null
        return fresh
    }

    /** 点击路径用：签名还新鲜就复用，过期/缺失就换一张新的。 */
    suspend fun usableSignature(): FileSignature? {
        val cached = signature
        if (cached != null && !FileSignatureFreshness.isStale(signedAtMs, System.currentTimeMillis())) {
            return cached
        }
        return refreshSignature()
    }

    // 只在图片卡片上组合期先签一次：图片要立即拿到 URL 才能开始加载；
    // 音频/视频/普通文件是「点击才用」，集中在那时签（否则一屏 N 张卡片会打 N 个
    // /files/sign，而且每张卡片都会闪一下「正在获取文件授权…」）。
    LaunchedEffect(card.path) {
        if (signFile != null && IMAGE_KINDS.contains(card.kind)) refreshSignature()
    }

    /** 用户动作：期间给「在准备」的反馈，避免慢网络下「点了没反应」。 */
    fun runAction(block: suspend () -> Unit) {
        scope.launch {
            actionPending = true
            try {
                block()
            } finally {
                actionPending = false
            }
        }
    }

    fun openExternally(url: String) {
        try {
            // NEW_TASK：Compose 的 LocalContext 不保证是 Activity，缺少这个 flag 时
            // startActivity 会直接抛 AndroidRuntimeException（下载按钮看似没反应）。
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
        } catch (_: ActivityNotFoundException) {
            error = "没有可用的浏览器打开该文件"
        } catch (_: Exception) {
            error = "打开文件失败，请重试"
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        when {
            IMAGE_KINDS.contains(card.kind) -> ImageFileCardView(
                card = card,
                viewUrl = signature?.let { signedUrl("view", it) },
                pending = signing,
            )

            AUDIO_KINDS.contains(card.kind) -> AudioFileCardView(
                card = card,
                onPlay = {
                    runAction { usableSignature()?.let { playingUrl = signedUrl("view", it) } }
                },
                onDownload = {
                    runAction { usableSignature()?.let { openExternally(signedUrl("download", it)) } }
                },
            )

            VIDEO_KINDS.contains(card.kind) -> VideoFileCardView(
                card = card,
                onPlay = {
                    runAction { usableSignature()?.let { openExternally(signedUrl("view", it)) } }
                },
                onDownload = {
                    runAction { usableSignature()?.let { openExternally(signedUrl("download", it)) } }
                },
            )

            else -> GenericFileCardView(
                card = card,
                onDownload = {
                    runAction { usableSignature()?.let { openExternally(signedUrl("download", it)) } }
                },
            )
        }

        // 首次签名（图片卡片）或用户点击后正在换签：都得有「在准备」的可见反馈。
        if (actionPending || (signing && signature == null)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                CircularProgressIndicator(modifier = Modifier.size(12.dp), strokeWidth = 2.dp)
                Text(
                    "正在获取文件授权…",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        error?.let { message ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    message,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.error,
                )
                TextButton(onClick = { runAction { refreshSignature() } }) {
                    Text("重试", style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }

    playingUrl?.let { url ->
        AudioPlayerDialog(
            title = card.title ?: card.filename,
            url = url,
            // 播放中签名过期/请求失败时，换一张新签名再试一次。
            onNeedFreshUrl = { usableSignature()?.let { signedUrl("view", it) } },
            onDismiss = { playingUrl = null },
        )
    }
}

@Composable
private fun ImageFileCardView(card: FileCard, viewUrl: String?, pending: Boolean) {
    var showLightbox by remember { mutableStateOf(false) }

    Column {
        Surface(
            modifier = Modifier
                .sizeIn(maxWidth = 240.dp, maxHeight = 180.dp)
                .clip(MaterialTheme.shapes.small)
                // 没有签名 URL 时不给点：点了也是打开一张 404/401 的图。
                .clickable(enabled = viewUrl != null) { showLightbox = true },
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f),
        ) {
            if (viewUrl != null) {
                AsyncImage(
                    model = viewUrl,
                    contentDescription = card.title ?: card.filename,
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.sizeIn(maxWidth = 240.dp, maxHeight = 180.dp),
                )
            } else {
                Box(
                    modifier = Modifier.size(160.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    if (pending) {
                        CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(
                            Icons.Default.BrokenImage,
                            contentDescription = "图片加载失败",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
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

    if (showLightbox && viewUrl != null) {
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
        shape = MaterialTheme.shapes.small,
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
        shape = MaterialTheme.shapes.small,
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
        shape = MaterialTheme.shapes.small,
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
