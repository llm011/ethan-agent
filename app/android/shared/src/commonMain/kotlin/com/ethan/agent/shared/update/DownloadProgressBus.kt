package com.ethan.agent.shared.update

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 后台下载的进度广播：`ApkDownloadService`（在 `:app`）写，`UpdateViewModel`
 * （在 `:shared`）读。
 *
 * 为什么要这个中转：下载跑在**前台服务**里（切后台/息屏也能继续），而进度要显示在
 * **页面**上。两者生命周期完全独立 —— 页面可能在下载中途被销毁再重建，服务也可能
 * 在页面退出后继续跑。用一个进程级单例 StateFlow 把两边解耦，比 Binder /
 * BroadcastReceiver 简单得多，且重建页面时能立刻拿到当前进度（StateFlow 有当前值）。
 *
 * 局限（有意接受）：**只在单进程内有效**。如果进程被系统杀掉，服务一起死，
 * 进度也一起没了 —— 但那种情况下用户在通知栏也看不到东西，没有「进度错乱」的问题：
 * 页面重建时会看到 [DownloadStatus.Idle]，用户可以重新点更新，`.part` 文件还在，
 * 会从断点续传。
 */
object DownloadProgressBus {

    sealed interface DownloadStatus {
        data object Idle : DownloadStatus
        data class Running(val progress: Int) : DownloadStatus

        /** 下载并校验完成，等待触发安装器。 */
        data object Downloaded : DownloadStatus

        /** 所有源都失败了。 */
        data class Failed(val message: String) : DownloadStatus
    }

    private val _status = MutableStateFlow<DownloadStatus>(DownloadStatus.Idle)
    val status: StateFlow<DownloadStatus> = _status.asStateFlow()

    fun update(status: DownloadStatus) {
        _status.value = status
    }

    fun reset() {
        _status.value = DownloadStatus.Idle
    }
}
