package com.ethan.agent.ui.docs

import com.ethan.agent.shared.viewmodel.DocsUiState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Article
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ethan.agent.ui.components.EthanCard
import com.ethan.agent.ui.components.EthanEmptyState
import com.ethan.agent.ui.components.EthanListRow
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SimpleMarkdown
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DocsScreen(
    state: DocsUiState,
    onBack: () -> Unit = {},
    onSelectDoc: (String) -> Unit,
    onClearError: () -> Unit,
    showListOnly: Boolean = false,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    Scaffold(
        topBar = { EthanTopBar(title = "文档", onBack = onBack) },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        if (state.isLoading) {
            LoadingBox(Modifier.padding(padding))
            return@Scaffold
        }

        if (showListOnly || state.selectedSlug == null) {
            if (state.docs.isEmpty()) {
                EthanEmptyState(
                    title = "还没有文档",
                    description = "让 Ethan 帮你写点东西，文档会出现在这里",
                    icon = Icons.AutoMirrored.Filled.Article,
                    modifier = Modifier.padding(padding),
                )
            } else {
                // 分组容器 + 统一列表行：标题、图标、chevron 齐了，靠分隔线成组，
                // 不再是「一堆各自独立、没有任何视觉信息的小卡片」。
                LazyColumn(
                    modifier = Modifier.fillMaxSize().padding(padding),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    item {
                        DocListCard(count = state.docs.size) {
                            state.docs.forEachIndexed { index, doc ->
                                if (index > 0) {
                                    androidx.compose.material3.HorizontalDivider(
                                        modifier = Modifier.padding(start = 46.dp),
                                        color = MaterialTheme.colorScheme.outlineVariant,
                                    )
                                }
                                EthanListRow(
                                    title = doc.title.ifBlank { doc.slug },
                                    subtitle = doc.filename.takeIf { it.isNotBlank() && it != doc.title },
                                    icon = Icons.AutoMirrored.Filled.Article,
                                    onClick = { onSelectDoc(doc.slug) },
                                    trailing = {
                                        Icon(
                                            Icons.AutoMirrored.Filled.KeyboardArrowRight,
                                            contentDescription = null,
                                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    },
                                )
                            }
                        }
                    }
                }
            }
        } else {
            Column(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
            ) {
                if (state.content.isBlank()) {
                    EthanEmptyState(
                        title = "这篇文档还是空的",
                        description = "内容为空",
                    )
                } else {
                    SimpleMarkdown(text = state.content)
                }
            }
        }
    }
}

/** 文档列表外层的分组卡片，带一个「N 篇」的计数标题。 */
@Composable
private fun DocListCard(count: Int, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Text(
            text = "共 $count 篇",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 4.dp, bottom = 6.dp),
        )
        EthanCard { Column(Modifier.padding(vertical = 4.dp)) { content() } }
    }
}
