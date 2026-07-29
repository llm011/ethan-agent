package com.ethan.agent.ui.schedule

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.ScheduleJob
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanScrollableTabBar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduleScreen(
    state: ScheduleUiState,
    onBack: () -> Unit = {},
    onToggle: (ScheduleJob) -> Unit,
    onDelete: (String) -> Unit,
    onTrigger: (ScheduleJob) -> Unit,
    onOpenSession: (String) -> Unit,
    onTabChange: (ScheduleTab) -> Unit,
    onSyncTimelines: () -> Unit,
    onTimelineAction: (String, String) -> Unit,
    onShowCreateSheet: () -> Unit,
    onDismissCreateSheet: () -> Unit,
    onUpdateForm: (CreateScheduleForm) -> Unit,
    onSubmitCreate: () -> Unit,
    onClearError: () -> Unit,
    onClearTriggerSuccess: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    val triggerSuccess = state.triggerSuccess
    LaunchedEffect(triggerSuccess) {
        if (triggerSuccess == null) return@LaunchedEffect
        val result = snackbar.showSnackbar(
            message = "已触发，跳转到关联会话查看",
            actionLabel = if (triggerSuccess.sessionId.isNotBlank()) "查看" else null,
        )
        if (result == SnackbarResult.ActionPerformed && triggerSuccess.sessionId.isNotBlank()) {
            onOpenSession(triggerSuccess.sessionId)
        }
        onClearTriggerSuccess()
    }

    Scaffold(
        snackbarHost = { SnackbarContainer(snackbar) },
        floatingActionButton = {
            if (state.tab == ScheduleTab.Jobs) {
                FloatingActionButton(onClick = onShowCreateSheet) {
                    Icon(Icons.Default.Add, contentDescription = "创建任务")
                }
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            EthanTopBar(title = "定时任务", onBack = onBack)

            EthanScrollableTabBar(
                tabs = ScheduleTab.entries.toList(),
                selectedTab = state.tab,
                onTabSelected = onTabChange,
                labelOf = { it.title },
            )

            if (state.isLoading) {
                LoadingBox()
                return@Column
            }

            when (state.tab) {
                ScheduleTab.Jobs -> JobsContent(
                    jobs = state.jobs,
                    triggeringIds = state.triggeringIds,
                    onTrigger = onTrigger,
                    onToggle = onToggle,
                    onDelete = onDelete,
                    onOpenSession = onOpenSession,
                )
                ScheduleTab.Timelines -> TimelinesContent(
                    timelines = state.timelines,
                    isSyncing = state.isSyncingTimelines,
                    onSync = onSyncTimelines,
                    onAction = onTimelineAction,
                )
            }
        }

        if (state.showCreateSheet) {
            CreateScheduleSheet(
                form = state.createForm,
                isCreating = state.isCreating,
                onDismiss = onDismissCreateSheet,
                onUpdate = onUpdateForm,
                onSubmit = onSubmitCreate,
            )
        }
    }
}

@Composable
private fun JobsContent(
    jobs: List<ScheduleJob>,
    triggeringIds: Set<String>,
    onTrigger: (ScheduleJob) -> Unit,
    onToggle: (ScheduleJob) -> Unit,
    onDelete: (String) -> Unit,
    onOpenSession: (String) -> Unit,
) {
    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 12.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(jobs, key = { it.id }) { job ->
            JobCard(
                job = job,
                triggering = job.id in triggeringIds,
                onTrigger = { onTrigger(job) },
                onToggle = { onToggle(job) },
                onDelete = { onDelete(job.id) },
                onOpenSession = { onOpenSession(job.sessionId) },
            )
        }
    }
}

@Composable
private fun JobCard(
    job: ScheduleJob,
    triggering: Boolean,
    onTrigger: () -> Unit,
    onToggle: () -> Unit,
    onDelete: () -> Unit,
    onOpenSession: () -> Unit,
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(job.name, style = MaterialTheme.typography.titleMedium)
            Text(job.trigger, style = MaterialTheme.typography.bodySmall)
            job.nextRunTime?.let { Text("下次: $it", style = MaterialTheme.typography.labelSmall) }
            Text(
                if (job.status == "active") "运行中" else "已暂停",
                color = if (job.status == "active") MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.labelMedium,
            )
            Row(
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (job.sessionId.isNotBlank()) {
                    TextButton(onClick = onOpenSession) { Text("查看对话") }
                }
                IconButton(onClick = onTrigger, enabled = !triggering) {
                    if (triggering) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(Icons.Default.Bolt, contentDescription = "立即触发")
                    }
                }
                IconButton(onClick = onToggle) {
                    if (job.status == "active") {
                        Icon(Icons.Default.Pause, contentDescription = "暂停")
                    } else {
                        Icon(Icons.Default.PlayCircle, contentDescription = "恢复")
                    }
                }
                IconButton(onClick = onDelete) {
                    Icon(Icons.Default.Delete, contentDescription = "删除")
                }
            }
        }
    }
}

@Composable
private fun TimelinesContent(
    timelines: List<TimelineItem>,
    isSyncing: Boolean,
    onSync: () -> Unit,
    onAction: (String, String) -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedButton(onClick = onSync, enabled = !isSyncing) {
                if (isSyncing) {
                    CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(6.dp))
                }
                Icon(Icons.Default.Sync, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("同步")
            }
        }

        val grouped = timelines.groupBy { it.scene }
        LazyColumn(
            Modifier.fillMaxSize().padding(horizontal = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            grouped.forEach { (scene, items) ->
                item(key = "header_$scene") {
                    Text(
                        scene.ifBlank { "默认" },
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(vertical = 4.dp),
                    )
                }
                items(items, key = { it.id }) { timeline ->
                    TimelineCard(timeline = timeline, onAction = { action -> onAction(timeline.id, action) })
                }
            }
        }
    }
}

@Composable
private fun TimelineCard(timeline: TimelineItem, onAction: (String) -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(timeline.name, style = MaterialTheme.typography.titleMedium)
            timeline.currentPhase?.let { Text("当前阶段：$it", style = MaterialTheme.typography.bodySmall) }
            timeline.nextPhase?.let { Text("下一阶段：$it", style = MaterialTheme.typography.bodySmall) }
            if (timeline.nextAnchor.isNotBlank()) {
                Text("锚点：${timeline.nextAnchor}", style = MaterialTheme.typography.labelSmall)
            }
            Text(
                if (timeline.status == "active") "进行中" else "已暂停",
                color = if (timeline.status == "active") MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.labelMedium,
            )
            Row(
                Modifier.fillMaxWidth().padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                TextButton(onClick = { onAction("skip_phase") }) { Text("跳过") }
                TextButton(onClick = { onAction("advance_phase") }) { Text("进入下阶段") }
                if (timeline.status == "active") {
                    TextButton(onClick = { onAction("pause") }) { Text("暂停") }
                } else {
                    TextButton(onClick = { onAction("resume") }) { Text("恢复") }
                }
                TextButton(onClick = { onAction("cleanup") }) { Text("清理") }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CreateScheduleSheet(
    form: CreateScheduleForm,
    isCreating: Boolean,
    onDismiss: () -> Unit,
    onUpdate: (CreateScheduleForm) -> Unit,
    onSubmit: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 32.dp)
                .imePadding(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("创建定时任务", style = MaterialTheme.typography.titleLarge)

            OutlinedTextField(
                value = form.name,
                onValueChange = { onUpdate(form.copy(name = it)) },
                label = { Text("任务名称") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            OutlinedTextField(
                value = form.prompt,
                onValueChange = { onUpdate(form.copy(prompt = it)) },
                label = { Text("提示词") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
                maxLines = 6,
            )

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = form.triggerType == "cron",
                    onClick = { onUpdate(form.copy(triggerType = "cron")) },
                    label = { Text("Cron") },
                )
                FilterChip(
                    selected = form.triggerType == "interval",
                    onClick = { onUpdate(form.copy(triggerType = "interval")) },
                    label = { Text("间隔") },
                )
            }

            if (form.triggerType == "cron") {
                OutlinedTextField(
                    value = form.cron,
                    onValueChange = { onUpdate(form.copy(cron = it)) },
                    label = { Text("Cron 表达式") },
                    placeholder = { Text("0 9 * * 1-5") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
            } else {
                OutlinedTextField(
                    value = form.intervalMinutes,
                    onValueChange = { onUpdate(form.copy(intervalMinutes = it)) },
                    label = { Text("间隔（分钟）") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
            }

            OutlinedTextField(
                value = form.sessionId,
                onValueChange = { onUpdate(form.copy(sessionId = it)) },
                label = { Text("关联会话 ID（可选）") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            OutlinedTextField(
                value = form.category,
                onValueChange = { onUpdate(form.copy(category = it)) },
                label = { Text("分类（可选）") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            OutlinedTextField(
                value = form.scene,
                onValueChange = { onUpdate(form.copy(scene = it)) },
                label = { Text("场景（可选，默认 work）") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            Spacer(Modifier.height(4.dp))

            Button(
                onClick = onSubmit,
                enabled = !isCreating,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (isCreating) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text("创建")
            }
        }
    }
}
