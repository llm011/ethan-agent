package com.ethan.agent.ui.chat

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.Quote
import com.ethan.agent.data.UiMessage
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import com.ethan.agent.ui.components.ToolTimeline
import com.ethan.agent.ui.components.SimpleMarkdown
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    state: ChatUiState,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onModelSelected: (String) -> Unit,
    onModeSelected: (String) -> Unit,
    onQuote: (Quote?) -> Unit,
    onUpload: (File, String) -> Unit,
    onConsent: (Boolean) -> Unit,
    onDismissConsent: () -> Unit,
    onStop: () -> Unit,
    onOnboardingChange: (String, String) -> Unit,
    onCompleteOnboarding: () -> Unit,
    onDismissOnboarding: () -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    val listState = rememberLazyListState()
    val context = LocalContext.current

    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        val name = uri.lastPathSegment ?: "file"
        context.contentResolver.openInputStream(uri)?.use { input ->
            val temp = File(context.cacheDir, name)
            temp.outputStream().use { output -> input.copyTo(output) }
            onUpload(temp, name)
        }
    }

    LaunchedEffect(state.messages.size) {
        if (state.messages.isNotEmpty()) {
            listState.animateScrollToItem(state.messages.lastIndex)
        }
    }

    ErrorSnackbar(state.error, onClearError, snackbar)

    if (state.showOnboarding) {
        AlertDialog(
            onDismissRequest = onDismissOnboarding,
            title = { Text("欢迎使用 Ethan") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(state.onboarding?.message ?: "为你的 Agent 取个名字吧")
                    OutlinedTextField(
                        value = state.agentName,
                        onValueChange = { onOnboardingChange(it, state.userInfo) },
                        label = { Text("Agent 名称") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = state.userInfo,
                        onValueChange = { onOnboardingChange(state.agentName, it) },
                        label = { Text("自我介绍") },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                    )
                }
            },
            confirmButton = { TextButton(onClick = onCompleteOnboarding) { Text("完成") } },
            dismissButton = { TextButton(onClick = onDismissOnboarding) { Text("跳过") } },
        )
    }

    state.consent?.let { consent ->
        AlertDialog(
            onDismissRequest = onDismissConsent,
            title = { Text("需要授权: ${consent.tool}") },
            text = {
                Column {
                    Text(consent.description)
                    consent.detail?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                }
            },
            confirmButton = { TextButton(onClick = { onConsent(true) }) { Text("允许") } },
            dismissButton = { TextButton(onClick = { onConsent(false) }) { Text("拒绝") } },
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(title = { Text(state.title) })
        },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        if (state.isLoading) {
            LoadingBox(Modifier.padding(padding))
            return@Scaffold
        }

        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding(),
        ) {
            ModelModeBar(state, onModelSelected, onModeSelected)

            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).padding(horizontal = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                itemsIndexed(state.messages) { _, msg ->
                    MessageBubble(msg, onLongPress = {
                        onQuote(Quote(role = msg.role, content = msg.content))
                    })
                }
            }

            state.quote?.let { quote ->
                AssistChip(
                    onClick = {},
                    label = { Text("引用: ${quote.content.take(40)}…", maxLines = 1) },
                    trailingIcon = {
                        IconButton(onClick = { onQuote(null) }) {
                            Icon(Icons.Default.Close, contentDescription = "清除引用")
                        }
                    },
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
            }

            Row(
                Modifier.fillMaxWidth().padding(12.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                IconButton(onClick = { filePicker.launch("*/*") }) {
                    Icon(Icons.Default.AttachFile, contentDescription = "附件")
                }
                OutlinedTextField(
                    value = state.inputText,
                    onValueChange = onInputChange,
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("输入消息，/help 查看命令") },
                    maxLines = 5,
                )
                if (state.isStreaming) {
                    IconButton(onClick = onStop) {
                        Icon(Icons.Default.Stop, contentDescription = "停止")
                    }
                } else {
                    IconButton(onClick = onSend, enabled = state.inputText.isNotBlank()) {
                        Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "发送")
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ModelModeBar(
    state: ChatUiState,
    onModelSelected: (String) -> Unit,
    onModeSelected: (String) -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        var modelExpanded by remember { mutableStateOf(false) }
        ExposedDropdownMenuBox(expanded = modelExpanded, onExpandedChange = { modelExpanded = it }) {
            AssistChip(
                onClick = { modelExpanded = true },
                label = { Text(state.selectedModel ?: "选择模型", maxLines = 1) },
                modifier = Modifier.menuAnchor().weight(1f),
            )
            ExposedDropdownMenu(expanded = modelExpanded, onDismissRequest = { modelExpanded = false }) {
                state.models.forEach { model ->
                    DropdownMenuItem(
                        text = { Text(model.id) },
                        onClick = {
                            onModelSelected(model.id)
                            modelExpanded = false
                        },
                    )
                }
            }
        }

        state.modes.forEach { mode ->
            FilterChip(
                selected = state.selectedMode == mode.key,
                onClick = { onModeSelected(if (state.selectedMode == mode.key) "" else mode.key) },
                label = { Text(mode.label) },
            )
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageBubble(message: UiMessage, onLongPress: () -> Unit) {
    val isUser = message.role == "user"
    val alignment = if (isUser) Alignment.CenterEnd else Alignment.CenterStart
    val bg = if (isUser) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant

    Box(Modifier.fillMaxWidth(), contentAlignment = alignment) {
        Card(
            modifier = Modifier
                .widthIn(max = 320.dp)
                .combinedClickable(onClick = {}, onLongClick = onLongPress),
            shape = RoundedCornerShape(16.dp),
        ) {
            Column(
                Modifier.background(bg).padding(12.dp),
            ) {
                message.quote?.let {
                    Text(
                        "↩ ${it.content.take(60)}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.padding(2.dp))
                }
                if (message.content.isNotBlank()) {
                    SimpleMarkdown(text = message.content)
                }
                if (message.isStreaming && message.content.isEmpty()) {
                    Text("思考中…", style = MaterialTheme.typography.bodySmall)
                }
                if (message.toolSteps.isNotEmpty()) {
                    ToolTimeline(message.toolSteps)
                }
                message.usage?.let {
                    Text(
                        "tokens: ${it.input}+${it.output}",
                        style = MaterialTheme.typography.labelSmall,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }
        }
    }
}