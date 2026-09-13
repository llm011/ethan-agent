package com.ethan.agent.ui.components

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.ethan.agent.shared.viewmodel.UpdateViewModel
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import android.widget.Toast
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay

/**
 * 全局更新提示组件。
 * 在 MainContent 中挂载一次，根据 UpdateViewModel 状态自动显示/隐藏。
 */
@Composable
fun UpdateDialog(viewModel: UpdateViewModel) {
    val state by viewModel.state.collectAsState()
    val context = LocalContext.current

    // 通知权限（API 33+）。**在用户点「下载并安装」的那一刻申请**，而不是启动时冷冰冰
    // 弹一个 —— 那时用户刚看到「可以切后台继续下载」，能理解为什么要这个权限。
    //
    // 拒绝也不影响功能：前台服务不依赖通知权限，只是通知不显示（下载照常跑，
    // UpdateDialog 里的进度条也照常走）。所以这里**不做任何「必须授权」的引导**。
    val notificationPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* 授不授权都不拦下载 */ }

    // 应用启动后延迟 30s 自动检查
    LaunchedEffect(Unit) {
        delay(30_000)
        viewModel.autoCheck()
    }

    // "已是最新版本" 用 Toast 反馈，避免手动检查时无任何响应
    LaunchedEffect(state) {
        if (state is UpdateViewModel.UpdateState.UpToDate) {
            Toast.makeText(context, "已是最新版本", Toast.LENGTH_SHORT).show()
        }
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
                    TextButton(onClick = {
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                            ContextCompat.checkSelfPermission(
                                context,
                                Manifest.permission.POST_NOTIFICATIONS,
                            ) != PackageManager.PERMISSION_GRANTED
                        ) {
                            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                        }
                        viewModel.downloadAndInstall(s.info)
                    }) {
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
                // 下载现在跑在前台服务里，切后台/息屏都会继续 —— 所以「先不管它」
                // 必须是个能走的选项，否则用户会被一个关不掉的对话框困住。
                onDismissRequest = viewModel::dismiss,
                title = { Text("正在下载更新") },
                text = {
                    Column {
                        LinearProgressIndicator(
                            progress = { s.progress / 100f },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        // 百分比与说明同一行：进度条已经把「多少」表达清楚了，
                        // 再单独占一行会跟下面的按钮之间留下一大块空白。
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = "${s.progress}%",
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            Text(
                                text = "可以切到后台，下载会在通知栏继续",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(start = 12.dp),
                            )
                        }
                    }
                },
                confirmButton = {},
                dismissButton = {
                    TextButton(onClick = viewModel::dismiss) {
                        Text("后台下载")
                    }
                },
            )
        }

        // 后台下完了但用户当时不在页面 → 回来看到这个，点一下再装。
        // 不让系统安装器自己弹出来打断用户，也免得用户以为「没反应」。
        is UpdateViewModel.UpdateState.Downloaded -> {
            AlertDialog(
                onDismissRequest = viewModel::dismiss,
                title = { Text("更新包已就绪") },
                text = { Text("新版本已下载并校验完成，点按继续安装。") },
                confirmButton = {
                    TextButton(onClick = viewModel::installDownloaded) {
                        Text("安装")
                    }
                },
                dismissButton = {
                    TextButton(onClick = viewModel::dismiss) {
                        Text("稍后")
                    }
                },
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

        is UpdateViewModel.UpdateState.InstallPermissionRequired -> {
            AlertDialog(
                onDismissRequest = viewModel::dismiss,
                title = { Text("需要安装权限") },
                text = { Text("请先在系统设置中允许 Ethan 安装未知来源应用，然后返回应用重新点击更新。") },
                confirmButton = {
                    TextButton(onClick = viewModel::dismiss) {
                        Text("我知道了")
                    }
                },
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

        is UpdateViewModel.UpdateState.UpToDate -> {} // 静默，不弹窗

        else -> {} // Idle / Checking 不显示
    }
}
