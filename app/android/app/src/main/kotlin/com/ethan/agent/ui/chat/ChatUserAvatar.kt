package com.ethan.agent.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clip
import androidx.compose.material.icons.Icons
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.Dp
import coil.compose.SubcomposeAsyncImage
import androidx.compose.material.icons.filled.Person

/**
 * 把头像的相对路径（`assets/images/_profile/img_avatar.png`）拼成绝对 URL。
 *
 * 空串不拼（否则会拼出一个悬空 URL 再白白请求一次），已经是 http(s) 的原样返回。
 */
internal fun avatarAbsoluteUrl(path: String, serverUrl: String): String = when {
    path.isBlank() -> ""
    path.startsWith("http") -> path
    else -> "${serverUrl.trimEnd('/')}/$path"
}

/** 取名字首个码点并大写 —— 与共享包 avatarInitial 同语义（emoji 不能被切成半个代理对）。 */
internal fun userAvatarInitial(name: String): String {
    val trimmed = name.trim()
    if (trimmed.isEmpty()) return ""
    val first = trimmed.codePointAt(0)
    return String(Character.toChars(first)).uppercase()
}

/**
 * 头像本体：有图就显示图，图加载失败 / 没图但有名字显示首字，都没有显示人形图标。
 *
 * 图片和兜底在**同一个** `SubcomposeAsyncImage` 里切换，而不是在外面用 `painter.state`
 * 判断再换组合 —— 后者会让「图加载成功」和「兜底」成为两棵树，加载完成的一瞬间
 * 整个头像被替换掉，圆角/尺寸会闪一下。
 *
 * 刻意不设 contentDescription：头像纯装饰，气泡里已有正文，读屏再念一遍是噪声。
 */
@Composable
internal fun UserAvatarImage(
    url: String,
    name: String,
    size: Dp,
    modifier: Modifier = Modifier,
) {
    val shape = CircleShape
    val initial = remember(name) { userAvatarInitial(name) }
    val fallback: @Composable () -> Unit = {
        if (initial.isNotBlank()) {
            Box(
                modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.primary.copy(alpha = 0.15f)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    initial,
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.titleSmall,
                )
            }
        } else {
            Box(
                modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Filled.Person,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(size * 0.55f),
                )
            }
        }
    }

    Box(modifier = modifier.size(size).clip(shape)) {
        if (url.isBlank()) {
            // 没设头像：直接兜底，连请求都不发（Coil 拿到空串会走一次无效加载）
            fallback()
        } else {
            SubcomposeAsyncImage(
                model = url,
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
                loading = { fallback() },
                error = { fallback() },
            )
        }
    }
}
