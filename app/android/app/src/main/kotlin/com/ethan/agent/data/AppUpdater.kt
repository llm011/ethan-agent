package com.ethan.agent.data

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Android 应用内自更新。
 *
 * 流程：检查 GitHub Releases → 比较版本号 → 下载 APK → 触发系统安装器。
 * 所有错误静默吞掉，不打断正常使用。
 */
@Singleton
class AppUpdater @Inject constructor(
    @ApplicationContext private val context: Context,
) {

    companion object {
        private const val GITHUB_API =
            "https://api.github.com/repos/llm011/ethan-agent/releases/latest"
        private const val APK_CACHE_NAME = "ethan-update.apk"
        private const val PREF_NAME = "app_update"
        private const val KEY_LAST_CHECK = "last_check_ts"
        private const val CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000L // 4 小时
    }

    data class UpdateInfo(
        val version: String,
        val downloadUrl: String,
        val releaseNotes: String,
        val htmlUrl: String,
    )

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    private val prefs by lazy {
        context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
    }

    /** 当前是否应该检查更新（距上次检查超过 4 小时）。 */
    fun shouldCheck(): Boolean {
        val last = prefs.getLong(KEY_LAST_CHECK, 0)
        return System.currentTimeMillis() - last > CHECK_INTERVAL_MS
    }

    /**
     * 检查 GitHub 上是否有比当前版本更新的 release。
     * @return UpdateInfo 或 null（无更新 / 无 APK / 网络错误）。
     */
    suspend fun checkForUpdate(): UpdateInfo? = withContext(Dispatchers.IO) {
        try {
            prefs.edit().putLong(KEY_LAST_CHECK, System.currentTimeMillis()).apply()

            val currentVersion = getCurrentVersion() ?: return@withContext null

            val request = Request.Builder()
                .url(GITHUB_API)
                .header("Accept", "application/vnd.github+json")
                .header("User-Agent", "Ethan-Android")
                .build()

            val response = client.newCall(request).execute()
            if (!response.isSuccessful) return@withContext null

            val json = JSONObject(response.body?.string() ?: return@withContext null)
            val tagName = json.optString("tag_name").removePrefix("v").trim()
            if (tagName.isEmpty()) return@withContext null

            // 版本号没变或更低，不提示
            if (compareVersions(tagName, currentVersion) <= 0) return@withContext null

            // 在 assets 里找 .apk 文件
            val assets = json.optJSONArray("assets") ?: return@withContext null
            var apkUrl: String? = null
            for (i in 0 until assets.length()) {
                val asset = assets.optJSONObject(i) ?: continue
                val name = asset.optString("name")
                if (name.endsWith(".apk", ignoreCase = true)) {
                    apkUrl = asset.optString("browser_download_url")
                    break
                }
            }
            if (apkUrl.isNullOrEmpty()) return@withContext null

            UpdateInfo(
                version = tagName,
                downloadUrl = apkUrl,
                releaseNotes = json.optString("body").ifBlank { "暂无更新说明" },
                htmlUrl = json.optString("html_url"),
            )
        } catch (_: Exception) {
            null
        }
    }

    /**
     * 下载 APK 到 cacheDir。
     * @param onProgress 进度回调 0-100。
     * @return 下载好的 File，失败返回 null。
     */
    suspend fun downloadApk(url: String, onProgress: (Int) -> Unit): File? =
        withContext(Dispatchers.IO) {
            try {
                val request = Request.Builder().url(url).build()
                val response = client.newCall(request).execute()
                if (!response.isSuccessful) return@withContext null

                val body = response.body ?: return@withContext null
                val totalBytes = body.contentLength()

                val apkFile = File(context.cacheDir, APK_CACHE_NAME)
                body.byteStream().use { input ->
                    apkFile.outputStream().use { output ->
                        val buffer = ByteArray(8192)
                        var bytesRead: Int
                        var downloaded = 0L
                        while (input.read(buffer).also { bytesRead = it } != -1) {
                            output.write(buffer, 0, bytesRead)
                            downloaded += bytesRead
                            if (totalBytes > 0) {
                                onProgress((downloaded * 100 / totalBytes).toInt().coerceIn(0, 100))
                            }
                        }
                    }
                }
                onProgress(100)
                apkFile
            } catch (_: Exception) {
                null
            }
        }

    sealed class InstallResult {
        data object Triggered : InstallResult()
        data object PermissionRequired : InstallResult()
    }

    /** 用 FileProvider + Intent 触发系统安装器。Android 8+ 先检查安装未知来源权限。 */
    fun installApk(apkFile: File): InstallResult {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (!context.packageManager.canRequestPackageInstalls()) {
                val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES).apply {
                    data = Uri.parse("package:${context.packageName}")
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                context.startActivity(intent)
                return InstallResult.PermissionRequired
            }
        }
        val uri = FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            apkFile,
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
        return InstallResult.Triggered
    }

    private fun getCurrentVersion(): String? = try {
        context.packageManager
            .getPackageInfo(context.packageName, 0)
            .versionName
    } catch (_: Exception) {
        null
    }

    /**
     * 语义版本比较：返回 >0 表示 v1 更新，<0 表示 v2 更新，0 表示相同。
     * prerelease 后缀（如 1.2.3-rc1）的数字段取前缀整数，后缀视为低于正式版。
     */
    private fun compareVersions(v1: String, v2: String): Int {
        // 把 "1.2.3-rc1" 拆成 numeric=[1,2,3], pre="rc1"
        fun parse(v: String): Pair<List<Int>, String> {
            val dashIdx = v.indexOf('-')
            val numeric = (if (dashIdx < 0) v else v.substring(0, dashIdx))
                .split(".")
                .map { it.toIntOrNull() ?: 0 }
            val pre = if (dashIdx < 0) "" else v.substring(dashIdx + 1)
            return numeric to pre
        }

        val (parts1, pre1) = parse(v1)
        val (parts2, pre2) = parse(v2)
        val maxLen = maxOf(parts1.size, parts2.size)
        for (i in 0 until maxLen) {
            val p1 = parts1.getOrElse(i) { 0 }
            val p2 = parts2.getOrElse(i) { 0 }
            if (p1 != p2) return p1 - p2
        }
        // 数字段相同：无 prerelease 后缀 > 有 prerelease 后缀（1.2.3 > 1.2.3-rc1）
        return when {
            pre1.isEmpty() && pre2.isEmpty() -> 0
            pre1.isEmpty() -> 1
            pre2.isEmpty() -> -1
            else -> comparePrerelease(pre1, pre2)
        }
    }

    /**
     * prerelease 后缀比较：>0 表示 a 更新，<0 表示 b 更新，0 表示相同。
     *
     * 按点号分段，每段拆成 "非数字前缀 + 数字后缀"：
     * - 前缀相同则数字后缀按整数比较，避免 "rc10" < "rc9" 的字典序错误
     * - 前缀不同则按 [PRERELEASE_PRIORITY] 语义序比较
     * - 段数多的更新（rc1.alpha2 > rc1）
     *
     * 仅匹配 "前缀+数字" 形式（如 rc10、beta2、alpha1）；纯字母或纯数字
     * 段走字典序兜底。
     */
    private fun comparePrerelease(a: String, b: String): Int {
        val segA = a.split(".")
        val segB = b.split(".")
        val n = minOf(segA.size, segB.size)
        for (i in 0 until n) {
            val sa = segA[i]
            val sb = segB[i]
            val ma = Regex("^(\\D*)(\\d+)$").matchEntire(sa)
            val mb = Regex("^(\\D*)(\\d+)$").matchEntire(sb)
            if (ma != null && mb != null) {
                val pa = ma.groupValues[1]
                val pb = mb.groupValues[1]
                if (pa != pb) return comparePrereleasePrefix(pa, pb)
                val na = ma.groupValues[2].toInt()
                val nb = mb.groupValues[2].toInt()
                if (na != nb) return na - nb
            } else {
                return sa.compareTo(sb)
            }
        }
        return segA.size - segB.size
    }

    /**
     * 常见 prerelease 前缀的语义优先级（数值越大越接近正式版）。
     * 覆盖 dev / alpha / beta / milestone / rc / preview / snapshot 等
     * 常见命名；未命中的前缀回退字典序（semver spec 规定非数字 identifier
     * 用 ASCII 字典序，这里对未知前缀保持 spec 兼容）。
     */
    private fun comparePrereleasePrefix(a: String, b: String): Int {
        val pa = PRERELEASE_PRIORITY[a]
        val pb = PRERELEASE_PRIORITY[b]
        if (pa != null && pb != null) return pa - pb
        // 至少一方不在表内：已知方优先（视为更接近正式版），双方均未知回退字典序
        if (pa != null) return 1
        if (pb != null) return -1
        return a.compareTo(b)
    }

    private companion object {
        /** 常见 prerelease 前缀 → 优先级（越大越接近正式版）。 */
        val PRERELEASE_PRIORITY = mapOf(
            "dev" to 0,
            "alpha" to 1,
            "a" to 1,
            "beta" to 2,
            "b" to 2,
            "milestone" to 3,
            "m" to 3,
            "mvp" to 3,
            "rc" to 4,
            "cr" to 4,
            "preview" to 5,
            "pre" to 5,
            "snapshot" to 0,
            "nightly" to 0,
        )
    }
}
