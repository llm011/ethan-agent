package com.ethan.agent.ui.components

import android.media.AudioAttributes
import android.media.MediaPlayer
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.PauseCircle
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private enum class AudioPlayerState { Preparing, Ready, Failed }

/**
 * 应用内音频播放器（深度听书交付的 MP3 用它播，不再把音频丢给外部浏览器 ——
 * 安卓上浏览器拿到 mp3 直链通常是「下载」而不是「播放」）。
 *
 * 状态机：Preparing → Ready / Failed，失败一定给出口（重试按钮），绝不无限转圈。
 * 播放失败先换一张新签名重试一次（签名 10 分钟过期是最常见的失败原因），
 * 仍失败才落到错误态。
 */
@Composable
internal fun AudioPlayerDialog(
    title: String,
    url: String,
    onNeedFreshUrl: suspend () -> String?,
    onDismiss: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val player = remember { MediaPlayer() }

    var state by remember { mutableStateOf(AudioPlayerState.Preparing) }
    var playing by remember { mutableStateOf(false) }
    var positionMs by remember { mutableIntStateOf(0) }
    var durationMs by remember { mutableIntStateOf(0) }
    var refreshedOnce by remember { mutableStateOf(false) }

    fun prepare(source: String) {
        state = AudioPlayerState.Preparing
        playing = false
        positionMs = 0
        runCatching {
            player.reset()
            player.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            player.setDataSource(source)
            player.prepareAsync()
        }.onFailure {
            state = AudioPlayerState.Failed
        }
    }

    DisposableEffect(url) {
        player.setOnPreparedListener { mp ->
            durationMs = mp.duration.coerceAtLeast(0)
            state = AudioPlayerState.Ready
            mp.start()
            playing = true
        }
        player.setOnCompletionListener {
            playing = false
            positionMs = durationMs
        }
        // 返回 true = 已处理，MediaPlayer 不会再往上抛（否则会走到 onCompletion）。
        player.setOnErrorListener { _, _, _ ->
            playing = false
            state = AudioPlayerState.Failed
            true
        }
        prepare(url)
        onDispose {
            runCatching { player.reset() }
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            runCatching { player.release() }
        }
    }

    // MediaPlayer 没有进度回调，只能轮询（播放中每 500ms 刷新一次进度条）。
    LaunchedEffect(state, playing) {
        while (state == AudioPlayerState.Ready && playing) {
            positionMs = runCatching { player.currentPosition }.getOrDefault(positionMs)
            delay(500)
        }
    }

    fun retry() {
        scope.launch {
            if (refreshedOnce) {
                prepare(url)
                return@launch
            }
            refreshedOnce = true
            val fresh = onNeedFreshUrl()
            if (fresh != null) prepare(fresh) else state = AudioPlayerState.Failed
        }
    }

    Dialog(onDismissRequest = { onDismiss() }) {
        Surface(shape = MaterialTheme.shapes.large, tonalElevation = 6.dp) {
            Column(
                modifier = Modifier.fillMaxWidth().padding(20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(
                    Icons.Default.GraphicEq,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(28.dp),
                )
                Text(
                    title,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    textAlign = TextAlign.Center,
                )

                when (state) {
                    AudioPlayerState.Preparing -> {
                        Text(
                            "音频加载中…",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
                    }

                    AudioPlayerState.Failed -> {
                        Text(
                            "音频加载失败，可能是网络问题或文件授权已过期",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                            textAlign = TextAlign.Center,
                        )
                        TextButton(onClick = { retry() }) { Text("重试") }
                    }

                    AudioPlayerState.Ready -> {
                        Slider(
                            value = positionMs.toFloat(),
                            onValueChange = { value ->
                                positionMs = value.toInt()
                                runCatching { player.seekTo(positionMs) }
                            },
                            valueRange = 0f..durationMs.toFloat().coerceAtLeast(1f),
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(formatClock(positionMs), style = MaterialTheme.typography.labelSmall)
                            Text(formatClock(durationMs), style = MaterialTheme.typography.labelSmall)
                        }
                        IconButton(
                            onClick = {
                                if (playing) {
                                    runCatching { player.pause() }
                                    positionMs = runCatching { player.currentPosition }.getOrDefault(positionMs)
                                    playing = false
                                } else {
                                    // 播完后再点播放：从头开始，否则 MediaPlayer 停在结尾没反应。
                                    if (durationMs > 0 && positionMs >= durationMs) {
                                        positionMs = 0
                                    }
                                    runCatching { player.seekTo(positionMs) }
                                    runCatching { player.start() }
                                    playing = true
                                }
                            },
                            modifier = Modifier.size(56.dp),
                        ) {
                            Icon(
                                if (playing) Icons.Default.PauseCircle else Icons.Default.PlayCircle,
                                contentDescription = if (playing) "暂停" else "播放",
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(48.dp),
                            )
                        }
                    }
                }

                TextButton(onClick = { onDismiss() }) { Text("关闭") }
            }
        }
    }
}

private fun formatClock(ms: Int): String {
    val totalSeconds = (ms.coerceAtLeast(0)) / 1000
    val minutes = totalSeconds / 60
    val seconds = totalSeconds % 60
    return "$minutes:${seconds.toString().padStart(2, '0')}"
}
