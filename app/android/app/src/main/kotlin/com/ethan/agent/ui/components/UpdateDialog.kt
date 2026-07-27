package com.ethan.agent.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import kotlinx.coroutines.delay

/**
 * 全局更新提示组件。
 * 在 MainContent 中挂载一次，根据 UpdateViewModel 状态自动显示/隐藏。
 */
@Composable
fun UpdateDialog(viewModel: UpdateViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsState()

    // 应用启动后延迟 30s 自动检查
    LaunchedEffect(Unit) {
        delay(30_000)
        viewModel.autoCheck()
    }

    when (val s = state) {
        is UpdateViewModel.UpdateState.Available -> {
            AlertDialog(
                onDismissRequest = viewModel::dismiss,
                title = {
                    Text("发现新版本 v${s.info.version}")
                },
                text = {
                    Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                        Text(
                            text = s.info.releaseNotes,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                },
                confirmButton = {
                    TextButton(onClick = { viewModel.downloadAndInstall(s.info) }) {
                        Text("下载并安装")
                    }
                },
                dismissButton = {
                    TextButton(onClick = viewModel::dismiss) {
                        Text("稍后")
                    }
                },
            )
        }

        is UpdateViewModel.UpdateState.Downloading -> {
            AlertDialog(
                onDismissRequest = {},
                title = { Text("正在下载更新") },
                text = {
                    Column {
                        LinearProgressIndicator(
                            progress = { s.progress / 100f },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Text(
                            text = "${s.progress}%",
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.padding(top = 8.dp),
                        )
                    }
                },
                confirmButton = {},
                dismissButton = {},
            )
        }

        is UpdateViewModel.UpdateState.Installing -> {
            AlertDialog(
                onDismissRequest = {},
                title = { Text("正在安装") },
                text = { Text("安装界面已打开，请按提示完成安装。") },
                confirmButton = {},
                dismissButton = {},
            )
        }

        is UpdateViewModel.UpdateState.Error -> {
            AlertDialog(
                onDismissRequest = viewModel::clearError,
                title = { Text("更新失败") },
                text = { Text(s.message) },
                confirmButton = {
                    TextButton(onClick = viewModel::checkForUpdate) {
                        Text("重试")
                    }
                },
                dismissButton = {
                    TextButton(onClick = viewModel::clearError) {
                        Text("关闭")
                    }
                },
            )
        }

        is UpdateViewModel.UpdateState.UpToDate -> {
            AlertDialog(
                onDismissRequest = viewModel::dismiss,
                title = { Text("已是最新版本") },
                text = { Text("当前使用的版本已经是最新的了。") },
                confirmButton = {
                    TextButton(onClick = viewModel::dismiss) {
                        Text("好的")
                    }
                },
            )
        }

        else -> {} // Idle / Checking 不显示
    }
}
