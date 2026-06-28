package com.ethan.agent.ui.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.AutoStories
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ViewList
import androidx.compose.ui.graphics.vector.ImageVector

sealed class Screen(val route: String, val title: String, val icon: ImageVector? = null) {
    data object Login : Screen("login", "登录")
    data object Setup : Screen("setup", "连接配置")
    data object Chat : Screen("chat?sessionId={sessionId}", "对话", Icons.AutoMirrored.Filled.Chat) {
        fun createRoute(sessionId: String? = null) =
            if (sessionId != null) "chat?sessionId=$sessionId" else "chat"
    }
    data object Sessions : Screen("sessions", "全部对话", Icons.Default.ViewList)
    data object Memory : Screen("memory", "记忆", Icons.Default.Psychology)
    data object Knowledge : Screen("knowledge", "知识库", Icons.Default.MenuBook)
    data object Skills : Screen("skills", "技能", Icons.Default.Extension)
    data object Schedule : Screen("schedule", "定时任务", Icons.Default.Schedule)
    data object Settings : Screen("settings", "设置", Icons.Default.Settings)
    data object Docs : Screen("docs", "文档", Icons.Default.AutoStories)
    data object DocDetail : Screen("docs/{slug}", "文档详情")
    data object Logs : Screen("logs", "日志")
    data object More : Screen("more", "更多", Icons.Default.MoreHoriz)
}

val bottomNavItems = listOf(
    Screen.Chat,
    Screen.Sessions,
    Screen.More,
    Screen.Settings,
)

val moreMenuItems = listOf(
    Screen.Memory,
    Screen.Knowledge,
    Screen.Skills,
    Screen.Schedule,
    Screen.Docs,
    Screen.Logs,
)
