package com.ethan.agent.data

import android.content.Context
import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.shared.AppUpdater as SharedAppUpdater

class AndroidAppUpdater(
    private val context: Context,
    configStore: AppConfigStore? = null,
) : SharedAppUpdater {
    private val delegate = AppUpdater(context, configStore)

    override fun shouldCheck(): Boolean = delegate.shouldCheck()

    override suspend fun checkForUpdate(): SharedAppUpdater.CheckResult {
        return when (val result = delegate.checkForUpdate()) {
            is AppUpdater.CheckResult.UpdateAvailable -> SharedAppUpdater.CheckResult.UpdateAvailable(
                SharedAppUpdater.UpdateInfo(
                    version = result.info.version,
                    downloadUrl = result.info.downloadUrl,
                    releaseNotes = result.info.releaseNotes,
                    htmlUrl = result.info.htmlUrl,
                    downloadUrls = result.info.downloadUrls,
                    sha256 = result.info.sha256,
                    sizeBytes = result.info.sizeBytes,
                )
            )
            is AppUpdater.CheckResult.UpToDate -> SharedAppUpdater.CheckResult.UpToDate
            is AppUpdater.CheckResult.Error -> SharedAppUpdater.CheckResult.Error(result.message)
        }
    }

    /**
     * 把下载交给 [ApkDownloadService]（前台服务）后**立刻返回**。
     *
     * 不在这里 `await` 下载结果：那样下载就绑死在 ViewModel 上，用户一切后台
     * 下载就断了 —— 而「升级很麻烦」的一大半正来自于此。进度走
     * [com.ethan.agent.shared.update.DownloadProgressBus]。
     *
     * `onProgress` 参数保留是为了兼容接口签名（iOS 那边是同步语义），
     * Android 这边不需要：进度由服务直接广播，比绕一层回调更准（服务可能在
     * 页面销毁后继续跑，回调此时根本无处可投）。
     */
    override suspend fun downloadAndInstall(
        info: SharedAppUpdater.UpdateInfo,
        onProgress: (Int) -> Unit,
    ): SharedAppUpdater.InstallResult {
        val urls = info.downloadUrls.ifEmpty { listOf(info.downloadUrl) }
        ApkDownloadService.start(
            context = context,
            version = info.version,
            urls = urls,
            sha256 = info.sha256,
            sizeBytes = info.sizeBytes,
        )
        return SharedAppUpdater.InstallResult.DownloadStarted
    }

    override suspend fun installDownloaded(): SharedAppUpdater.InstallResult {
        val apk = delegate.downloadedApkFile()
            ?: return SharedAppUpdater.InstallResult.Failed
        return when (delegate.installApk(apk)) {
            AppUpdater.InstallResult.Triggered -> SharedAppUpdater.InstallResult.Triggered
            AppUpdater.InstallResult.PermissionRequired -> SharedAppUpdater.InstallResult.PermissionRequired
        }
    }
}
