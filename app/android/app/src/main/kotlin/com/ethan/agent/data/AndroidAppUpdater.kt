package com.ethan.agent.data

import android.content.Context
import com.ethan.agent.shared.AppUpdater as SharedAppUpdater

class AndroidAppUpdater(context: Context) : SharedAppUpdater {
    private val delegate = AppUpdater(context)

    override fun shouldCheck(): Boolean = delegate.shouldCheck()

    override suspend fun checkForUpdate(): SharedAppUpdater.CheckResult {
        return when (val result = delegate.checkForUpdate()) {
            is AppUpdater.CheckResult.UpdateAvailable -> SharedAppUpdater.CheckResult.UpdateAvailable(
                SharedAppUpdater.UpdateInfo(
                    version = result.info.version,
                    downloadUrl = result.info.downloadUrl,
                    releaseNotes = result.info.releaseNotes,
                    htmlUrl = result.info.htmlUrl,
                )
            )
            is AppUpdater.CheckResult.UpToDate -> SharedAppUpdater.CheckResult.UpToDate
            is AppUpdater.CheckResult.Error -> SharedAppUpdater.CheckResult.Error(result.message)
        }
    }

    override suspend fun downloadAndInstall(url: String, onProgress: (Int) -> Unit): SharedAppUpdater.InstallResult {
        val apkFile = delegate.downloadApk(url, onProgress) ?: return SharedAppUpdater.InstallResult.Failed
        return when (delegate.installApk(apkFile)) {
            AppUpdater.InstallResult.Triggered -> SharedAppUpdater.InstallResult.Triggered
            AppUpdater.InstallResult.PermissionRequired -> SharedAppUpdater.InstallResult.PermissionRequired
        }
    }
}
