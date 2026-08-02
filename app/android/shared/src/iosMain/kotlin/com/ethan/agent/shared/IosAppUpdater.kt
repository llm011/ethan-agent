package com.ethan.agent.shared

/**
 * iOS 端 AppUpdater 实现：no-op。
 *
 * iOS 应用更新统一走 App Store，app 内不做自更新。所有方法返回"无需更新"，
 * 让 UpdateViewModel 的状态机走到 UpToDate 后自动消失，UI 不报错。
 *
 * 如后续需要对接 TestFlight / App Store Connect API 做版本提醒，
 * 在此处替换 checkForUpdate 实现即可，接口无需改动。
 */
object IosAppUpdater : AppUpdater {
    override fun shouldCheck(): Boolean = false
    override suspend fun checkForUpdate(): AppUpdater.CheckResult = AppUpdater.CheckResult.UpToDate
    override suspend fun downloadAndInstall(url: String, onProgress: (Int) -> Unit): AppUpdater.InstallResult =
        AppUpdater.InstallResult.Failed
}
