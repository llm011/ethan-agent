package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.shared.AppUpdater
import com.ethan.agent.shared.update.DownloadProgressBus
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class UpdateViewModel(
    private val appUpdater: AppUpdater,
) : ViewModel() {

    sealed class UpdateState {
        data object Idle : UpdateState()
        data object Checking : UpdateState()
        data class Available(val info: AppUpdater.UpdateInfo) : UpdateState()
        data class Downloading(val progress: Int) : UpdateState()

        /**
         * 下载并校验完成，等用户点「安装」。
         *
         * 这是个**独立的终态**（而不是自动滑到 Installing）：下载现在跑在后台服务里，
         * 完成时用户可能已经不在这个页面了；下次回来应该看到「下载好了，去安装」，
         * 而不是让系统安装器莫名其妙自己弹出来。
         */
        data object Downloaded : UpdateState()
        data object Installing : UpdateState()
        data object InstallPermissionRequired : UpdateState()
        data class Error(val message: String) : UpdateState()
        data object UpToDate : UpdateState()
    }

    private val _state = MutableStateFlow<UpdateState>(UpdateState.Idle)
    val state = _state.asStateFlow()

    init {
        // 下载在后台服务里跑，进度通过 DownloadProgressBus 广播回来。页面重建
        // （旋转 / 从后台回来）时会立刻拿到当前进度 —— StateFlow 有当前值，
        // 所以不会出现「下载其实在跑，但页面显示 Idle」。
        viewModelScope.launch {
            DownloadProgressBus.status.collect { status ->
                _state.value = when (status) {
                    is DownloadProgressBus.DownloadStatus.Idle -> {
                        // bus 说「没有下载在进行」，但页面可能正停在别的状态上 ——
                        // 只有「正在下载」才需要跟着回落到 Idle，其余状态一律保持
                        // （否则一次 reset 会把刚查到的 UpdateAvailable 也抹掉）。
                        if (_state.value is UpdateState.Downloading) UpdateState.Idle else _state.value
                    }
                    is DownloadProgressBus.DownloadStatus.Running ->
                        UpdateState.Downloading(status.progress)
                    is DownloadProgressBus.DownloadStatus.Downloaded -> UpdateState.Downloaded
                    is DownloadProgressBus.DownloadStatus.Failed -> UpdateState.Error(status.message)
                }
            }
        }
    }

    /** 应用启动后延迟自动检查（仅当距上次检查超过 4 小时）。 */
    fun autoCheck() {
        if (!appUpdater.shouldCheck()) return
        if (_state.value !is UpdateState.Idle) return
        checkForUpdate(silent = true)
    }

    /** 手动检查更新（忽略时间限制）。 */
    fun checkForUpdate(silent: Boolean = false) {
        if (_state.value is UpdateState.Checking) return
        if (_state.value is UpdateState.Downloading) return
        viewModelScope.launch {
            _state.value = UpdateState.Checking
            when (val result = appUpdater.checkForUpdate()) {
                is AppUpdater.CheckResult.UpdateAvailable -> {
                    _state.value = UpdateState.Available(result.info)
                }
                is AppUpdater.CheckResult.UpToDate -> {
                    if (silent) {
                        _state.value = UpdateState.Idle
                    } else {
                        _state.value = UpdateState.UpToDate
                        // "已是最新" 3 秒后自动消失
                        delay(3000)
                        if (_state.value is UpdateState.UpToDate) {
                            _state.value = UpdateState.Idle
                        }
                    }
                }
                is AppUpdater.CheckResult.Error -> {
                    if (silent) {
                        // 自动检查失败时静默，不打扰用户
                        _state.value = UpdateState.Idle
                    } else {
                        _state.value = UpdateState.Error(result.message)
                    }
                }
            }
        }
    }

    /**
     * 开始下载 APK。Android 上会把下载交给前台服务后立刻返回，
     * 进度由 [init] 里的 bus 订阅推着走，直到 [UpdateState.Downloaded]。
     */
    fun downloadAndInstall(info: AppUpdater.UpdateInfo) {
        if (_state.value is UpdateState.Downloading) return
        viewModelScope.launch {
            _state.value = UpdateState.Downloading(0)
            DownloadProgressBus.update(DownloadProgressBus.DownloadStatus.Running(0))
            when (appUpdater.downloadAndInstall(info) { /* 进度走 bus，见 init */ }) {
                // Android：已交给后台服务，状态由 bus 驱动
                is AppUpdater.InstallResult.DownloadStarted -> Unit
                is AppUpdater.InstallResult.Triggered -> {
                    // 同步语义的实现（老行为）：安装已触发，短暂停留再回 Idle
                    _state.value = UpdateState.Installing
                    delay(2000)
                    if (_state.value is UpdateState.Installing) {
                        _state.value = UpdateState.Idle
                    }
                }
                is AppUpdater.InstallResult.PermissionRequired -> {
                    _state.value = UpdateState.InstallPermissionRequired
                }
                is AppUpdater.InstallResult.Failed -> {
                    DownloadProgressBus.update(
                        DownloadProgressBus.DownloadStatus.Failed("下载失败，请稍后重试")
                    )
                }
            }
        }
    }

    /**
     * 把已下载好的 APK 交给系统安装器。
     *
     * 和 [downloadAndInstall] 分开：后台下载完成后用户可能已经离开页面，
     * 回来时是「下载好了，点这里安装」，而不是让安装器自己弹出来打断用户。
     */
    fun installDownloaded() {
        viewModelScope.launch {
            when (appUpdater.installDownloaded()) {
                is AppUpdater.InstallResult.Triggered -> {
                    _state.value = UpdateState.Installing
                    DownloadProgressBus.reset()
                    delay(2000)
                    if (_state.value is UpdateState.Installing) {
                        _state.value = UpdateState.Idle
                    }
                }
                is AppUpdater.InstallResult.PermissionRequired -> {
                    // 引导用户去开「安装未知来源」。下载好的包还在，回来点一次即可。
                    _state.value = UpdateState.InstallPermissionRequired
                }
                is AppUpdater.InstallResult.DownloadStarted -> Unit
                is AppUpdater.InstallResult.Failed -> {
                    // 文件不在了（被系统清缓存等）→ 回到可重试态
                    DownloadProgressBus.reset()
                    _state.value = UpdateState.Error("安装包已失效，请重新下载")
                }
            }
        }
    }

    /**
     * 关掉当前提示。
     *
     * **必须同时把 bus 复位**：[DownloadProgressBus] 是进程级单例，
     * 上次下载失败留下的 `Failed` 会一直挂着 —— 下次 ViewModel 重建时 `init` 里的
     * 订阅会立刻把它读出来当成本次状态，于是 `autoCheck()` 因为「状态不是 Idle」
     * 直接 return，更新检查从此再也不触发。用户看到的就是「点了几次都不检查了」。
     */
    fun dismiss() {
        DownloadProgressBus.reset()
        _state.value = UpdateState.Idle
    }

    fun clearError() = dismiss()
}
