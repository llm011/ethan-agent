package com.ethan.agent.shared

/**
 * 应用更新检查器接口。
 * Android 实现：检查 GitHub Releases → 下载 APK → 触发系统安装器。
 * iOS 实现：可对接 App Store 更新或留空。
 */
interface AppUpdater {
    data class UpdateInfo(
        val version: String,
        val downloadUrl: String,
        val releaseNotes: String,
        val htmlUrl: String,
    )

    sealed class InstallResult {
        data object Triggered : InstallResult()
        data object PermissionRequired : InstallResult()
        data object Failed : InstallResult()
    }

    fun shouldCheck(): Boolean
    suspend fun checkForUpdate(): UpdateInfo?

    /** 下载并安装；onProgress 回调 0-100。 */
    suspend fun downloadAndInstall(url: String, onProgress: (Int) -> Unit): InstallResult
}
