package com.ethan.agent.data

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import com.ethan.agent.BuildConfig
import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.shared.update.DownloadPlan
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Android 应用内自更新。
 *
 * 流程：检查 GitHub Releases → 比较版本号 → 下载 APK → 触发系统安装器。
 * 所有错误静默吞掉，不打断正常使用。
 */
class AppUpdater(
    private val context: Context,
    private val configStore: AppConfigStore? = null,
) {

    companion object {
        private const val GITHUB_API =
            "https://api.github.com/repos/llm011/ethan-agent/releases/latest"
        const val APK_CACHE_NAME = "ethan-update.apk"
        private const val PREF_NAME = "app_update"

        /** 侧车校验文件的后缀，与 CI 里生成的 `app-release.apk.sha256` 对应。 */
        private const val SHA256_ASSET_SUFFIX = ".apk.sha256"
        private const val KEY_LAST_CHECK = "last_check_ts"

        /** 上次下载对应的版本号；变了就把 `.part` 清掉（远端包换了，续不了）。 */
        private const val KEY_PART_TAG = "part_tag"
        private const val CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000L // 4 小时

        /** 常见 prerelease 前缀 → 优先级（越大越接近正式版）。 */
        private val PRERELEASE_PRIORITY = mapOf(
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

    data class UpdateInfo(
        val version: String,
        val downloadUrl: String,
        val releaseNotes: String,
        val htmlUrl: String,
        /** 候选源列表（CDN → 自建服务端 → GitHub），按可达性排序。 */
        val downloadUrls: List<String> = listOf(downloadUrl),
        /** GitHub Release 侧车 `app-release.apk.sha256`；老 release 没有则为 null。 */
        val sha256: String? = null,
        /** 远端 APK 字节数；未知为 0。 */
        val sizeBytes: Long = 0L,
    )

    sealed class CheckResult {
        data class UpdateAvailable(val info: UpdateInfo) : CheckResult()
        data object UpToDate : CheckResult()
        data class Error(val message: String) : CheckResult()
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    /**
     * 下载走**独立的 client**：这里 60s 的 readTimeout 是给流式接口用的，
     * 对分块下载太宽松（进度条卡住要等一分钟才报错）。
     */
    private val downloader by lazy { ApkDownloader(context) }

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
     * @return CheckResult 表示检查结果（有更新/已是最新/错误）。
     */
    suspend fun checkForUpdate(): CheckResult = withContext(Dispatchers.IO) {
        try {
            prefs.edit().putLong(KEY_LAST_CHECK, System.currentTimeMillis()).apply()

            val currentVersion = getCurrentVersion()
                ?: return@withContext CheckResult.Error("无法获取当前版本号")

            val request = Request.Builder()
                .url(checkApiUrl())
                .header("Accept", "application/vnd.github+json")
                .header("User-Agent", "Ethan-Android")
                .build()

            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                return@withContext CheckResult.Error("网络请求失败 (HTTP ${response.code})")
            }

            val body = response.body?.string()
                ?: return@withContext CheckResult.Error("服务器返回为空")

            val json = JSONObject(body)
            val tagName = json.optString("tag_name").removePrefix("v").trim()
            if (tagName.isEmpty()) {
                return@withContext CheckResult.Error("无法解析版本号")
            }

            // 版本号没变或更低，不提示
            if (compareVersions(tagName, currentVersion) <= 0) {
                return@withContext CheckResult.UpToDate
            }

            // 在 assets 里找 .apk 文件
            val assets = json.optJSONArray("assets")
                ?: return@withContext CheckResult.Error("Release 中没有安装包")

            var apkUrl: String? = null
            var apkSize = 0L
            var sha256Url: String? = null
            for (i in 0 until assets.length()) {
                val asset = assets.optJSONObject(i) ?: continue
                val name = asset.optString("name")
                val url = asset.optString("browser_download_url")
                when {
                    name.endsWith(".apk", ignoreCase = true) -> {
                        apkUrl = url
                        apkSize = asset.optLong("size", 0L)
                    }
                    name.endsWith(SHA256_ASSET_SUFFIX, ignoreCase = true) -> sha256Url = url
                }
            }

            if (apkUrl.isNullOrEmpty()) {
                return@withContext CheckResult.Error("Release 中没有 APK 安装包")
            }

            // 侧车校验值。**拿不到不算错误** —— 老 release 没有侧车，此时退化成
            // 「只校验长度」；为了一个可选的完整性增强而让用户更新不了是本末倒置。
            val sha256 = sha256Url?.let { fetchSha256(it) }

            // 三源候选列表：CDN（国内最快）→ 自建服务端（app 本来就连着它）→ GitHub（兜底）。
            // serverUrl 取不到时该源自动跳过，不影响更新可用性。
            val serverUrl = configStore?.let { store ->
                runCatching { store.config.first().serverUrl }.getOrNull()
            }
            val sources = BuildConfig.UPDATE_URL_OVERRIDE
                .takeIf { it.isNotBlank() }
                // 调试覆盖：把整个源列表替换成指定的地址（逗号分隔）。
                // 用来在本地复现「断点续传」和「换源」—— 这两条路径没法用真实源触发。
                ?.split(",")
                ?.map { it.trim() }
                ?.filter { it.isNotEmpty() }
                ?: DownloadPlan.candidateSources(
                    tag = tagName,
                    fallbackUrl = apkUrl,
                    serverUrl = serverUrl,
                )

            CheckResult.UpdateAvailable(UpdateInfo(
                version = tagName,
                downloadUrl = apkUrl,
                releaseNotes = json.optString("body").ifBlank { "暂无更新说明" },
                htmlUrl = json.optString("html_url"),
                downloadUrls = sources,
                sha256 = sha256,
                sizeBytes = apkSize,
            ))
        } catch (e: Exception) {
            CheckResult.Error("网络错误：${e.message ?: "未知错误"}")
        }
    }

    /**
     * 「检查更新」请求的 API 地址。debug 构建可用 `ETHAN_UPDATE_API_OVERRIDE` 指向
     * 本地桩服务器（模拟器没外网时唯一能跑通完整链路的方式）。release 恒为 GitHub。
     */
    private fun checkApiUrl(): String =
        BuildConfig.UPDATE_API_OVERRIDE.takeIf { it.isNotBlank() }
            ?: GITHUB_API

    /**
     * 读取侧车文件里的 sha256。失败返回 null（调用方退化成只校验长度）。
     *
     * 侧车内容就是 `sha256sum` 的输出：`<64 位小写 hex>  app-release.apk`。
     * 只取第一段 hex，不关心后面的文件名 —— 万一 CI 换了命名也不受影响。
     */
    private suspend fun fetchSha256(url: String): String? = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url(url)
                .header("User-Agent", "Ethan-Android")
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext null
                val text = response.body?.string() ?: return@withContext null
                val hex = text.trim().split(Regex("\\s+")).firstOrNull() ?: return@withContext null
                hex.takeIf { it.matches(Regex("^[0-9a-fA-F]{64}$")) }?.lowercase()
            }
        } catch (_: Exception) {
            null
        }
    }

    /**
     * 下载 APK 到 cacheDir：多源降级 + 断点续传 + 长度/sha256 校验 + 原子替换。
     *
     * 以前这里是「单次阻塞请求 + 8KB 拷贝循环，失败就 return null」，在国内网络下
     * 基本等于「断一次就得从头再来，而且没有任何诊断信息」。现在真正的执行在
     * [ApkDownloader]，失败后的决策在 [DownloadPlan]（已单测）。
     *
     * @param onProgress 进度回调 0-100。
     * @return 下载并校验通过的 File，失败返回 null。
     */
    suspend fun downloadApk(info: UpdateInfo, onProgress: (Int) -> Unit): File? {
        // `.part` 里可能有上一次（甚至上一个版本）的残留。tag 变了说明远端包换了，
        // 留着只会让 `Range` 请求一个已经不存在的位置 —— 清掉重来。
        val lastTag = prefs.getString(KEY_PART_TAG, null)
        if (lastTag != null && lastTag != info.version) {
            clearPartialDownloads()
        }
        prefs.edit().putString(KEY_PART_TAG, info.version).apply()

        val urls = info.downloadUrls.ifEmpty { listOf(info.downloadUrl) }
        return downloader.download(
            urls = urls,
            expectedSha256 = info.sha256,
            expectedSize = info.sizeBytes,
            onProgress = onProgress,
        )
    }

    /**
     * 已经下好并校验通过的 APK；没有则 null。
     *
     * 供「后台已经下完、用户过一会儿才回来点安装」这条路径使用 —— 那时手上没有
     * [UpdateInfo]，只能按约定名去 cacheDir 找。
     */
    fun downloadedApkFile(): File? =
        File(context.cacheDir, APK_CACHE_NAME).takeIf { it.isFile && it.length() > 0 }

    /** 清掉所有中间产物（`.part` / `.etag`）。换版本时调用。 */
    private fun clearPartialDownloads() {
        runCatching {
            context.cacheDir.listFiles()?.forEach { f ->
                if (f.name.endsWith(".part") || f.name.endsWith(".etag")) f.delete()
            }
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
        // 调试覆盖（debug 构建专用），用来在真机上走通「发现新版本」这条路径。
        // release 构建里这个字段恒为空串。
        val fake = BuildConfig.FAKE_CURRENT_VERSION
        if (fake.isNotBlank()) {
            fake
        } else {
            context.packageManager
                .getPackageInfo(context.packageName, 0)
                .versionName
        }
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
}
