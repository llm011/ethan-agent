package com.ethan.agent.data

import android.content.Context
import com.ethan.agent.shared.update.AttemptOutcome
import com.ethan.agent.shared.update.DownloadPlan
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import kotlin.coroutines.coroutineContext

/**
 * APK 下载器：**只负责执行 IO**，所有「失败了下一步怎么办」的决策都在
 * [DownloadPlan]（纯逻辑、已单测）。
 *
 * 加这层的起因（实测，不是推测）：APK 只有 3.3 MB、好网络下 0.93 秒就下完，
 * 但用户「下载失败率很高」—— 根因是 `release-assets.githubusercontent.com`
 * 在国内可达性差，不是传输量。所以这里的每一件事都是冲着「链路不稳」去的：
 *
 * 1. **多源降级** —— CDN → 自建服务端 → GitHub，一个源连不上就换下一个；
 * 2. **断点续传** —— `Range` + `If-Range`，中断了从已落盘的位置接着下；
 * 3. **完整性校验** —— 长度 + sha256，防止拿到半截包或 CDN 上的坏缓存；
 * 4. **原子替换** —— 先写 `.part`，校验通过才 rename 成正式文件。
 *
 * 第 4 点加了续传之后**必须**有：`File.outputStream()` 会先用 O_TRUNC 截断，
 * 续传时那就把之前下的几百 KB 全清了；改成 `RandomAccessFile` 追加写 + 成功后才
 * rename，才能真正做到「要么是完整的包，要么什么都没有」。
 */
internal class ApkDownloader(
    private val context: Context,
    private val client: OkHttpClient = defaultClient(),
) {

    companion object {
        /** 读超时 30s：分块下载中 30 秒一个字节都没来，就可以判链路死了。 */
        private const val READ_TIMEOUT_SECONDS = 30L

        /** 写盘缓冲。8 KB 太小（3.3 MB 要 400 多次 syscall），64 KB 足够且不占内存。 */
        private const val BUFFER_SIZE = 64 * 1024

        /** 陈旧文件保留时长：7 天没动过的中间产物直接清掉。 */
        private const val STALE_FILE_MS = 7 * 24 * 60 * 60 * 1000L

        private const val PART_SUFFIX = ".part"
        private const val ETAG_SUFFIX = ".etag"

        /**
         * 下载专用 client。**不能复用 [AppUpdater] 里那个 60s readTimeout 的** ——
         * 那个是给流式接口用的，对分块下载太宽松（用户要盯着进度条干等 60 秒）。
         *
         * `callTimeout(0)`：总时长不设上限，由 [DownloadPlan] 的重试次数兜底；
         * 设了就变成「大文件必然超时」。
         */
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(READ_TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .callTimeout(0, TimeUnit.SECONDS)
            .followRedirects(true)   // GitHub 的 302 → release-assets 必需
            .build()
    }

    /**
     * 依次尝试 [urls] 里的每个源，直到拿到一个**通过校验**的 APK。
     *
     * @param expectedSha256 GitHub Release 侧车 `app-release.apk.sha256` 的内容；
     *                       老 release 没有侧车时为 null，此时**仍然做长度校验**。
     * @param expectedSize   远端文件字节数；未知传 0。
     * @param onProgress     0-100。**续传时起点不是 0 是对的**（分母是文件总长）。
     * @return 下载并校验成功的文件；所有源都失败返回 null。
     */
    suspend fun download(
        urls: List<String>,
        expectedSha256: String?,
        expectedSize: Long,
        onProgress: (Int) -> Unit,
    ): File? = withContext(Dispatchers.IO) {
        val sources = urls.filter { it.isNotBlank() }.distinct()
        if (sources.isEmpty()) return@withContext null

        cleanupStaleFiles()

        // `.part` 的文件名带上源下标 —— 换源即从头，不能把上一个源下的半截续过来。
        // 不带版本号是**有意**的：同一版本重试时要能复用已下载的字节。
        var sourceIndex = 0
        var attempts = 0
        var resumeFrom = 0L

        while (true) {
            coroutineContext.ensureActive()
            val url = sources.getOrNull(sourceIndex) ?: return@withContext null
            val partFile = partFileFor(sourceIndex)
            val etagFile = File(context.cacheDir, "ethan-update-$sourceIndex$ETAG_SUFFIX")

            // 换源（或首次）时本地残留的字节不属于这个源，必须丢掉
            if (resumeFrom == 0L) {
                partFile.delete()
                etagFile.delete()
            }

            // `outcome` 要能在校验失败时被改写：`Success` 只代表「HTTP 层面下完了」，
            // 校验没过说明这个包是坏的，得按 `Fatal` 上报才能触发换源。
            var outcome: AttemptOutcome = try {
                attempt(
                    url = url,
                    partFile = partFile,
                    etagFile = etagFile,
                    resumeFrom = resumeFrom,
                    // 上面元数据里的真实总长优先。**这个参数很关键**：服务端把
                    // 一个 200 响应截断时，它声明的 Content-Length 就是那个被截断的
                    // 长度 —— 只看响应头会把「下了 300000 / 3507071」误判成
                    // 「下完了」，然后校验失败、删掉已下的 300000 字节从头再来。
                    // 这正是「下载失败率高」的典型形态。
                    expectedTotal = expectedSize,
                    onProgress = onProgress,
                )
            } catch (e: CancellationException) {
                // 协程被取消（用户退出页面 / 服务被杀）不是「下载失败」，
                // 必须原样抛出，否则会被吞成 null 让上层以为该换源重试。
                throw e
            } catch (e: IOException) {
                // 网络中断（ReadTimeout / SocketException）—— 已落盘的字节要保住，
                // 下次原地续传。所以这里当作 Partial 而不是从头。
                AttemptOutcome.Partial(partFile.length())
            } catch (e: Exception) {
                AttemptOutcome.Fatal(e::class.java.simpleName)
            }

            if (outcome is AttemptOutcome.Success) {
                val verified = verify(partFile, expectedSha256, expectedSize)
                if (verified != null) {
                    onProgress(100)
                    return@withContext verified
                }
                // 校验没过：文件是坏的（截断 / CDN 坏缓存 / 半截拼包），
                // 重试同一个源没意义，删掉重来。
                //
                // ⚠️ **必须按 Fatal 上报，不能继续顶着 Success 往下走**：
                // `DownloadPlan.next()` 对 Success 的语义是「已经成功、不必再做什么」，
                // 会直接返回 `nextSourceIndex = null` 让整个下载放弃 ——
                // 后面两个源（自建服务端 / GitHub 兜底）根本不会被访问。
                // 表现就是首源返回了一个「长度对得上、sha256 对不上」的坏包时，
                // 用户看到「所有源都失败了」，正是多源降级要解决的问题。
                partFile.delete()
                outcome = DownloadPlan.onVerificationFailed()
            }

            attempts += 1
            val decision = DownloadPlan.next(
                sourceIndex = sourceIndex,
                attemptsOnSource = attempts,
                sourceCount = sources.size,
                outcome = outcome,
            )
            if (decision.delayMs > 0) delay(decision.delayMs)

            val next = decision.nextSourceIndex ?: return@withContext null
            if (next != sourceIndex) attempts = 0
            sourceIndex = next
            resumeFrom = decision.resumeFrom
        }

        @Suppress("UNREACHABLE_CODE")
        return@withContext null
    }

    /**
     * 一次尝试：发请求、把响应体写进 [partFile]。
     *
     * 返回值交给 [DownloadPlan.classifyCode] 定夺 —— 这里只把「状态码 + 落盘字节数 +
     * 远端总长」三个事实交上去，不自己下判断。
     */
    private suspend fun attempt(
        url: String,
        partFile: File,
        etagFile: File,
        resumeFrom: Long,
        expectedTotal: Long,
        onProgress: (Int) -> Unit,
    ): AttemptOutcome {
        val existing = if (resumeFrom > 0) partFile.length() else 0L
        val etag = if (existing > 0) etagFile.readTextIfExists() else null

        val request = Request.Builder()
            .url(url)
            .header("Accept", "application/octet-stream")
            .apply {
                if (existing > 0) {
                    header("Range", "bytes=$existing-")
                    // 远端文件变了就让它返回 200 全量，我们从头来（而不是把两个
                    // 不同版本的文件拼在一起）。
                    if (!etag.isNullOrBlank()) header("If-Range", etag)
                }
            }
            .build()

        val call = client.newCall(request)

        return suspendCancellableCoroutine { cont ->
            // 协程取消时必须 cancel 掉 socket，否则底层读写会一直挂着
            cont.invokeOnCancellation { runCatching { call.cancel() } }

            try {
                call.execute().use { response ->
                    val code = response.code
                    if (code !in 200..299) {
                        cont.resumeWith(Result.success(
                            DownloadPlan.classifyCode(code, existing, totalOf(response, existing, expectedTotal))
                        ))
                        return@use
                    }

                    // 服务端忽略了 Range —— 它现在要发的其实是**整个文件**，
                    // 我们已经写进去的那截是「前半段属于别的版本」的垃圾，先清掉。
                    val serverIgnoredRange = existing > 0 && code == 200
                    val startAt = if (serverIgnoredRange) 0L else existing
                    if (serverIgnoredRange) {
                        partFile.delete()
                        etagFile.delete()
                    }

                    val total = totalOf(response, startAt, expectedTotal)
                    response.header("ETag")?.takeIf { it.isNotBlank() }?.let {
                        runCatching { etagFile.writeText(it) }
                    }

                    val body = response.body
                    if (body == null) {
                        cont.resumeWith(Result.success(AttemptOutcome.Partial(startAt)))
                        return@use
                    }

                    var written = startAt
                    RandomAccessFile(partFile, "rw").use { raf ->
                        raf.seek(startAt)
                        body.byteStream().use { input ->
                            val buffer = ByteArray(BUFFER_SIZE)
                            while (true) {
                                val n = input.read(buffer)
                                if (n <= 0) break
                                raf.write(buffer, 0, n)
                                written += n
                                if (total > 0) {
                                    onProgress(((written * 100) / total).toInt().coerceIn(0, 100))
                                }
                                // 取消后立刻停手，不等读完整个文件
                                if (cont.isCancelled) throw CancellationException("download cancelled")
                            }
                        }
                    }

                    cont.resumeWith(Result.success(
                        DownloadPlan.classifyCode(
                            status = code,
                            bytesWritten = written,
                            expectedTotal = total,
                            // 只有真的发了 Range 头，服务端返回 200 才意味着「它无视了续传请求」；
                            // 没发过 Range 的 200 只是「服务器把响应截断了」，两者处理方式相反。
                            resumeWasRequested = existing > 0,
                        )
                    ))
                }
            } catch (e: CancellationException) {
                if (!cont.isCancelled) cont.resumeWith(Result.failure(e))
            } catch (e: IOException) {
                // 连接中断时**已写盘的字节是有效的**，交给上层决定续传还是换源
                if (cont.isCancelled) {
                    cont.resumeWith(Result.success(AttemptOutcome.Partial(partFile.length())))
                } else {
                    cont.resumeWith(Result.failure(e))
                }
            } catch (e: Exception) {
                cont.resumeWith(Result.failure(e))
            }
        }
    }

    /**
     * 远端文件总长，按可信度从高到低取。
     *
     * 1. **调用方给的 `expectedTotal`**（Release 元数据里声明的 APK 大小）——
     *    唯一不受「服务端怎么回复」影响的值。响应头里的长度都可能骗人：被截断的
     *    200 响应会声称 `Content-Length` 就是它发出来的那一小段。
     * 2. `Content-Range`（`bytes 100000-3507070/3507071`）—— 206 的权威总长。
     *    比 `Content-Length` 可靠：206 里的 `Content-Length` 是**这一段**的长度，
     *    拿它当总长会让进度条永远停在 100% 之前；chunked 更没有 `Content-Length`。
     * 3. `Content-Length`（仅当从 0 开始写、且拿不到前两者时兜底）。
     *
     * 返回 0 表示「确实不知道」—— 调用方据此不能判定成功。
     */
    private fun totalOf(response: Response, fallbackStart: Long, expectedTotal: Long): Long {
        if (expectedTotal > 0) return expectedTotal

        response.header("Content-Range")
            ?.substringAfter('/', missingDelimiterValue = "")
            ?.trim()
            ?.toLongOrNull()
            ?.takeIf { it > 0 }
            ?.let { return it }

        val length = response.body?.contentLength() ?: -1
        if (length > 0 && fallbackStart == 0L) return length
        return 0
    }

    /**
     * 长度 + sha256 双校验，通过才把 `.part` 提升为正式文件。
     *
     * 校验失败会把 `.part` 删掉：留着它下次也不会续（长度都不对），
     * 反而会在磁盘上攒垃圾。
     */
    private fun verify(partFile: File, expectedSha256: String?, expectedSize: Long): File? {
        if (!partFile.exists()) return null

        if (expectedSize > 0 && partFile.length() != expectedSize) return null

        if (!expectedSha256.isNullOrBlank()) {
            val actual = sha256(partFile) ?: return null
            if (!actual.equals(expectedSha256.trim(), ignoreCase = true)) return null
        }

        val target = File(context.cacheDir, AppUpdater.APK_CACHE_NAME)
        if (target.exists()) target.delete()
        return if (partFile.renameTo(target)) target else null
    }

    private fun sha256(file: File): String? = try {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(BUFFER_SIZE)
            while (true) {
                val n = input.read(buffer)
                if (n <= 0) break
                digest.update(buffer, 0, n)
            }
        }
        digest.digest().joinToString("") { "%02x".format(it) }
    } catch (_: Exception) {
        null
    }

    /** 清理陈旧中间文件。**不动** `ethan-update.apk` 本身（正在用的包）。 */
    private fun cleanupStaleFiles() {
        val cutoff = System.currentTimeMillis() - STALE_FILE_MS
        runCatching {
            context.cacheDir.listFiles()?.forEach { f ->
                val name = f.name
                val isIntermediate = name.endsWith(PART_SUFFIX) || name.endsWith(ETAG_SUFFIX)
                if (isIntermediate && f.lastModified() < cutoff) f.delete()
            }
        }
    }

    private fun partFileFor(index: Int): File =
        File(context.cacheDir, "ethan-update-$index.apk$PART_SUFFIX")

    private fun File.readTextIfExists(): String? =
        if (exists()) runCatching { readText() }.getOrNull() else null
}
