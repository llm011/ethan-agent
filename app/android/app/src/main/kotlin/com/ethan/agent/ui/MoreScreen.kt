package com.ethan.agent.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import com.ethan.agent.ui.components.EthanGroup
import com.ethan.agent.ui.components.EthanGroupDivider
import com.ethan.agent.ui.components.EthanListRow
import com.ethan.agent.ui.components.EthanSectionHeader
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ethan.agent.ui.navigation.Screen

// Group items by category
private data class ToolGroup(val title: String, val items: List<Screen>)

private val toolGroups = listOf(
    ToolGroup("智能助手", listOf(Screen.Memory, Screen.Knowledge, Screen.Skills)),
    ToolGroup("自动化", listOf(Screen.Agenda, Screen.Schedule)),
    ToolGroup("资料", listOf(Screen.Docs)),
)

@Composable
fun MoreScreen(onNavigate: (String) -> Unit) {
    Scaffold(
        topBar = {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.surface,
            ) {
                Text(
                    text = "工具箱",
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                )
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            toolGroups.forEach { group ->
                ToolSection(title = group.title, items = group.items, onNavigate = onNavigate)
            }
        }
    }
}

@Composable
private fun ToolSection(title: String, items: List<Screen>, onNavigate: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        EthanSectionHeader(title = title)
        // 分组容器 + 统一列表行（与抽屉共用 EthanListRow，替代两份重复实现）。
        EthanGroup {
            items.forEachIndexed { index, screen ->
                if (index > 0) EthanGroupDivider()
                EthanListRow(
                    title = screen.title,
                    icon = screen.icon,
                    onClick = { onNavigate(screen.route) },
                )
            }
        }
    }
}
