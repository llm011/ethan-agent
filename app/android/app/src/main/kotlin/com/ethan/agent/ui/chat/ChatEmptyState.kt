package com.ethan.agent.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ethan.agent.R

@Composable
internal fun EmptyChatState(
    modifier: Modifier = Modifier,
    onQuickAction: (String) -> Unit,
) {
    val quickActions = listOf(
        "☀️ 深圳的天气怎么样" to "深圳的天气怎么样",
        "📄 帮我找找最新的 Agent 论文" to "帮我找找最新的 Agent 论文",
    )
    // 键盘弹出后 imePadding() 把整个 Column 压缩，而这里内容固定约 330dp 高：
    // 居中布局会把溢出部分均匀切掉两头，第二个提示文字（副标题）刚好落在上边缘
    // 被切一半（用户反馈）。改为「可滚动 + 靠上（CenterVertically 改为 Top）」：
    //   - Top 对齐：空间够时内容整体上移，副标题不会顶到上边缘；
    //   - verticalScroll：空间不够时（横屏 / 键盘弹起）用户能自己滑，不会静默丢内容。
    val scrollState = rememberScrollState()
    Column(
        modifier = modifier
            .wrapContentHeight(Alignment.Top)
            .verticalScroll(scrollState)
            .padding(horizontal = 24.dp, vertical = 30.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // 头像 - 圆形 app logo
        Image(
            painter = painterResource(id = R.drawable.ethan_logo_avatar),
            contentDescription = "Ethan",
            modifier = Modifier.size(72.dp).clip(CircleShape),
        )
        Text(
            text = "嗨，我是 Ethan~",
            style = MaterialTheme.typography.titleLarge,
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = FontWeight.Bold,
        )
        Text(
            text = "你的私人 AI 小助手，随时待命",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.padding(top = 4.dp),
        ) {
            quickActions.forEach { (label, payload) ->
                Surface(
                    onClick = { onQuickAction(payload) },
                    shape = MaterialTheme.shapes.extraLarge,
                    color = MaterialTheme.colorScheme.surfaceContainerLow,
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                ) {
                    Text(
                        text = label,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}
