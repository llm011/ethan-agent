package com.ethan.agent.data

import android.content.Context
import com.ethan.agent.shared.AppUpdater as SharedAppUpdater

class AndroidAppUpdater(context: Context) : SharedAppUpdater {
    private val delegate = AppUpdater(context)

    override fun shouldCheck(): Boolean = delegate.shouldCheck()

    override suspend fun checkForUpdate(): SharedAppUpdater.UpdateInfo? {
        val info = delegate.checkForUpdate() ?: return null
        return SharedAppUpdater.UpdateInfo(
            version = info.version,
            downloadUrl = info.downloadUrl,
            releaseNotes = info.releaseNotes,
            htmlUrl = info.htmlUrl,
        )
    }

    override suspend fun downloadAndInstall(url: String, onProgress: (Int) -> Unit): SharedAppUpdater.InstallResult {
        val apkFile = delegate.downloadApk(url, onProgress) ?: return SharedAppUpdater.InstallResult.Failed
        return when (delegate.installApk(apkFile)) {
            AppUpdater.InstallResult.Triggered -> SharedAppUpdater.InstallResult.Triggered
            AppUpdater.InstallResult.PermissionRequired -> SharedAppUpdater.InstallResult.PermissionRequired
        }
    }
}
