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
        /**
         * 候选下载源，按可达性排序（CDN → 自建服务端 → GitHub）。
         *
         * 新字段全部带默认值，老调用方零改动。默认值 `listOf(downloadUrl)` 保证
         * 「只有一个源」时行为和以前完全一致。
         */
        val downloadUrls: List<String> = listOf(downloadUrl),
        /** APK 的 sha256（来自 Release 侧车文件）；没有则为 null，只做长度校验。 */
        val sha256: String? = null,
        /** APK 字节数；未知为 0。 */
        val sizeBytes: Long = 0L,
    )

    sealed class CheckResult {
        data class UpdateAvailable(val info: UpdateInfo) : CheckResult()
        data object UpToDate : CheckResult()
        data class Error(val message: String) : CheckResult()
    }

    sealed class InstallResult {
        data object Triggered : InstallResult()
        data object PermissionRequired : InstallResult()
        data object Failed : InstallResult()

        /**
         * 下载已交给后台服务，进度会通过
         * [com.ethan.agent.shared.update.DownloadProgressBus] 广播回来。
         *
         * 为什么不让 `downloadAndInstall` 一直挂起到下载结束：那样下载就绑死在
         * ViewModel 的生命周期上，用户一切后台/退出页面下载就断了 —— 而这恰恰是
         * 「升级很麻烦」里最烦人的一环。Android 实现返回这个；iOS 不用（no-op）。
         */
        data object DownloadStarted : InstallResult()
    }

    fun shouldCheck(): Boolean
    suspend fun checkForUpdate(): CheckResult

    /**
     * 下载并安装；onProgress 回调 0-100。
     *
     * 传整个 [UpdateInfo] 而不是一个 url：多源降级需要完整的候选列表 +
     * sha256 + 期望长度，这些都在 info 里。调用方（[com.ethan.agent.shared.viewmodel.UpdateViewModel]）
     * 本来就持有 info，改成传引用是零成本的。
     *
     * Android 实现会**立刻**返回 [InstallResult.DownloadStarted]（下载转到前台服务），
     * 后续进度走 [com.ethan.agent.shared.update.DownloadProgressBus]；
     * 其余实现（iOS no-op）仍然是同步语义。
     */
    suspend fun downloadAndInstall(info: UpdateInfo, onProgress: (Int) -> Unit): InstallResult

    /**
     * 把已下载好的 APK 交给系统安装器。
     *
     * 拆出来是因为后台下载让「下载完成」和「触发安装」不再连续：服务在后台下完之后
     * 用户可能已经退出页面了，下次回到页面才点「安装」。此时手上只有
     * [com.ethan.agent.shared.update.DownloadProgressBus.DownloadStatus.Downloaded]，
     * 没有 info，所以这个动作不能依赖 info。
     */
    suspend fun installDownloaded(): InstallResult
}
