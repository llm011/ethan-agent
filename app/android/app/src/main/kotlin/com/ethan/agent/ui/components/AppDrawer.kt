package com.ethan.agent.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.Surface
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ethan.agent.core.model.SessionInfo
import com.ethan.agent.ui.navigation.Screen

private data class DrawerToolItem(val screen: Screen, val label: String)

private val drawerToolItems = listOf(
    DrawerToolItem(Screen.Memory, "记忆 Memory"),
    DrawerToolItem(Screen.Knowledge, "知识库 Knowledge"),
    DrawerToolItem(Screen.Skills, "技能 Skills"),
    DrawerToolItem(Screen.Agenda, "日程 Agenda"),
    DrawerToolItem(Screen.Schedule, "定时任务 Schedule"),
    DrawerToolItem(Screen.BackgroundTasks, "后台任务 Tasks"),
    DrawerToolItem(Screen.Docs, "文档 Docs"),
    DrawerToolItem(Screen.Settings, "设置 Settings"),
)

@Composable
fun AppDrawerContent(
    sessions: List<SessionInfo>,
    unreadSessionIds: Set<String> = emptySet(),
    onNewChat: () -> Unit,
    onSessionClick: (String) -> Unit,
    onSearchClick: () -> Unit,
    onNavigate: (String) -> Unit,
    onClose: () -> Unit,
) {
    // 分组：最近对话(非定时非心跳)、定时任务对话、心跳对话
    val recentSessions = remember(sessions) {
        sessions.filter { it.source != "scheduled" && it.source != "heartbeat" }.take(5)
    }
    val scheduledSessions = remember(sessions) {
        sessions.filter { it.source == "scheduled" }.take(5)
    }
    val heartbeatSessions = remember(sessions) {
        sessions.filter { it.source == "heartbeat" }.take(5)
    }

    // 计算每组未读数
    val recentUnread = remember(recentSessions, unreadSessionIds) {
        recentSessions.count { it.id in unreadSessionIds }
    }
    val scheduledUnread = remember(scheduledSessions, unreadSessionIds) {
        scheduledSessions.count { it.id in unreadSessionIds }
    }
    val heartbeatUnread = remember(heartbeatSessions, unreadSessionIds) {
        heartbeatSessions.count { it.id in unreadSessionIds }
    }

    ModalDrawerSheet(
        modifier = Modifier.fillMaxHeight().width(300.dp),
        drawerShape = RoundedCornerShape(0.dp),
        drawerContainerColor = MaterialTheme.colorScheme.surface,
    ) {
        Column(
            modifier = Modifier
                .fillMaxHeight()
                .verticalScroll(rememberScrollState())
                .padding(vertical = 16.dp),
        ) {
            // Header: "全部对话" (可点击) + search + new chat
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "全部对话",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier
                        .weight(1f)
                        .clickable(
                            indication = null,
                            interactionSource = remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
                        ) { onSearchClick(); onClose() },
                )
                IconButton(onClick = { onSearchClick(); onClose() }) {
                    Icon(
                        Icons.Default.Search,
                        contentDescription = "搜索",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                IconButton(onClick = { onNewChat(); onClose() }) {
                    Icon(
                        Icons.Default.Add,
                        contentDescription = "新对话",
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
            }

            Spacer(Modifier.height(8.dp))

            // 最新对话 — 默认展开
            CollapsibleSessionGroup(
                title = "最新对话",
                sessions = recentSessions,
                unreadCount = recentUnread,
                unreadSessionIds = unreadSessionIds,
                defaultExpanded = true,
                onSessionClick = { id -> onSessionClick(id); onClose() },
            )

            // 定时任务(对话) — 默认折叠
            CollapsibleSessionGroup(
                title = "定时任务(对话)",
                sessions = scheduledSessions,
                unreadCount = scheduledUnread,
                unreadSessionIds = unreadSessionIds,
                defaultExpanded = false,
                onSessionClick = { id -> onSessionClick(id); onClose() },
            )

            // 心跳(对话) — 默认折叠
            CollapsibleSessionGroup(
                title = "心跳(对话)",
                sessions = heartbeatSessions,
                unreadCount = heartbeatUnread,
                unreadSessionIds = unreadSessionIds,
                defaultExpanded = false,
                onSessionClick = { id -> onSessionClick(id); onClose() },
            )

            Spacer(Modifier.height(12.dp))
            HorizontalDivider(
                modifier = Modifier.padding(horizontal = 16.dp),
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
            )
            Spacer(Modifier.height(12.dp))

            // Tool navigation items
            drawerToolItems.forEach { item ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onNavigate(item.screen.route); onClose() }
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.6f),
                        modifier = Modifier.size(32.dp),
                    ) {
                        item.screen.icon?.let { icon ->
                            Icon(
                                imageVector = icon,
                                contentDescription = null,
                                modifier = Modifier.padding(6.dp),
                                tint = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                    Text(
                        text = item.label,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }

            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun CollapsibleSessionGroup(
    title: String,
    sessions: List<SessionInfo>,
    unreadCount: Int,
    unreadSessionIds: Set<String>,
    defaultExpanded: Boolean,
    onSessionClick: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(defaultExpanded) }

    // Section header row
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { expanded = !expanded }
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f),
        )

        // 红色未读数 badge
        if (unreadCount > 0) {
            Box(
                modifier = Modifier
                    .size(20.dp)
                    .clip(CircleShape)
                    .background(Color(0xFFE53935)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = if (unreadCount > 9) "9+" else unreadCount.toString(),
                    color = Color.White,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            Spacer(Modifier.width(8.dp))
        }

        // 展开/折叠图标
        Icon(
            imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ChevronRight,
            contentDescription = if (expanded) "收起" else "展开",
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp),
        )
    }

    // Session list with animation
    AnimatedVisibility(
        visible = expanded,
        enter = expandVertically(),
        exit = shrinkVertically(),
    ) {
        Column {
            sessions.forEach { session ->
                val hasUnread = session.id in unreadSessionIds
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onSessionClick(session.id) }
                        .padding(horizontal = 24.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // 未读红点
                    if (hasUnread) {
                        Box(
                            modifier = Modifier
                                .size(8.dp)
                                .clip(CircleShape)
                                .background(Color(0xFFE53935)),
                        )
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(
                        text = session.title.ifBlank { "未命名对话" },
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        fontWeight = if (hasUnread) FontWeight.SemiBold else FontWeight.Normal,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}
