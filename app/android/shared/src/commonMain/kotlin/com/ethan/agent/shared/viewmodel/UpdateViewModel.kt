package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.shared.AppUpdater
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
        data object Installing : UpdateState()
        data object InstallPermissionRequired : UpdateState()
        data class Error(val message: String) : UpdateState()
        data object UpToDate : UpdateState()
    }

    private val _state = MutableStateFlow<UpdateState>(UpdateState.Idle)
    val state = _state.asStateFlow()

    /** 应用启动后延迟自动检查（仅当距上次检查超过 4 小时）。 */
    fun autoCheck() {
        if (!appUpdater.shouldCheck()) return
        if (_state.value !is UpdateState.Idle) return
        checkForUpdate()
    }

    /** 手动检查更新（忽略时间限制）。 */
    fun checkForUpdate() {
        if (_state.value is UpdateState.Checking) return
        if (_state.value is UpdateState.Downloading) return
        viewModelScope.launch {
            _state.value = UpdateState.Checking
            val info = appUpdater.checkForUpdate()
            _state.value = if (info != null) {
                UpdateState.Available(info)
            } else {
                UpdateState.UpToDate
            }
            // "已是最新" 3 秒后自动消失
            if (_state.value is UpdateState.UpToDate) {
                delay(3000)
                if (_state.value is UpdateState.UpToDate) {
                    _state.value = UpdateState.Idle
                }
            }
        }
    }

    /** 下载 APK 并触发安装。 */
    fun downloadAndInstall(info: AppUpdater.UpdateInfo) {
        if (_state.value is UpdateState.Downloading) return
        viewModelScope.launch {
            _state.value = UpdateState.Downloading(0)
            _state.value = UpdateState.Installing
            when (appUpdater.downloadAndInstall(info.downloadUrl) { progress ->
                _state.value = UpdateState.Downloading(progress)
            }) {
                is AppUpdater.InstallResult.Triggered -> {
                    delay(2000)
                    if (_state.value is UpdateState.Installing) {
                        _state.value = UpdateState.Idle
                    }
                }
                is AppUpdater.InstallResult.PermissionRequired -> {
                    _state.value = UpdateState.InstallPermissionRequired
                }
                is AppUpdater.InstallResult.Failed -> {
                    _state.value = UpdateState.Error("下载失败，请稍后重试")
                }
            }
        }
    }

    fun dismiss() {
        _state.value = UpdateState.Idle
    }

    fun clearError() {
        if (_state.value is UpdateState.Error) {
            _state.value = UpdateState.Idle
        }
    }
}
