package com.ethan.agent.shared.update

/**
 * APK 下载的**决策逻辑**（纯函数，无 IO / 无 Android / 无 OkHttp 依赖）。
 *
 * 为什么要单独抽出来：下载失败在国内网络下是常态（GitHub 资产域名可达性差），
 * 所以「失败了下一步干什么」——原地重试？从头再来？换个源？——才是真正容易写错、
 * 也最需要回归保护的部分。[com.ethan.agent.data.ApkDownloader] 只负责按这里的
 * 决策去执行 IO，决策本身不碰网络，可在 `commonTest` 里零 mock 跑全分支。
 *
 * 对应仓库里既有的同类做法：`packages/shared/src/chat/history.ts` 也是把
 * 「分页怎么拼」从组件里剥成纯函数来测。
 */
sealed interface AttemptOutcome {
    /** 字节完整（长度/校验都过了）。 */
    data object Success : AttemptOutcome

    /**
     * 服务端忽略了 `Range`（返回 200 全量），或者返回 416（Range 越界 =
     * 远端文件变了）。两种情况都必须**丢掉已下载的字节从头来**。
     */
    data object NeedsRestart : AttemptOutcome

    /** 这次没下完，但**有进展**（已落盘 [bytesWritten] 字节），可以原地续传。 */
    data class Partial(val bytesWritten: Long) : AttemptOutcome

    /** 重试无意义的错误：校验失败 / 404 / 内容不对。直接换源，且从 0 开始。 */
    data class Fatal(val reason: String) : AttemptOutcome
}

/**
 * 「下一步怎么做」。
 *
 * @param nextSourceIndex 下一个要尝试的源下标；`null` = 放弃（所有源都用完了）。
 * @param resumeFrom 从第几个字节开始续；`0` = 从头下。
 * @param delayMs 这次尝试前等多久（退避，避免把已经拥塞的链路打得更死）。
 */
data class RetryDecision(
    val nextSourceIndex: Int?,
    val resumeFrom: Long,
    val delayMs: Long,
)

object DownloadPlan {

    /** 同一个源最多试几次（含首次）。超过就换源。 */
    const val MAX_ATTEMPTS_PER_SOURCE = 3

    /**
     * 退避间隔：1s → 3s。下标 = 已失败的次数 - 1。
     *
     * 只有 `attempts < MAX_ATTEMPTS_PER_SOURCE` 时才会走到退避（达到上限就直接换源、
     * 不再等待），所以这里最多只会取到第 2 项；多写的项是死代码。
     */
    private val BACKOFF_MS = longArrayOf(1_000, 3_000)

    /**
     * 给定「当前源下标 / 这个源上已经试了几次（含刚失败这次）/ 源总数 / 刚失败的结果」，
     * 算出下一步。
     *
     * @param attemptsOnSource 已经失败的次数（调用方在失败后 +1 再传进来）。
     */
    fun next(
        sourceIndex: Int,
        attemptsOnSource: Int,
        sourceCount: Int,
        outcome: AttemptOutcome,
    ): RetryDecision = when (outcome) {
        // 成了就不用再做什么了
        AttemptOutcome.Success -> RetryDecision(nextSourceIndex = null, resumeFrom = 0, delayMs = 0)

        // 服务端不支持续传 / 远端文件变了：本源从头再试，超上限就换源
        AttemptOutcome.NeedsRestart ->
            if (attemptsOnSource >= MAX_ATTEMPTS_PER_SOURCE) {
                switchSource(sourceIndex, sourceCount)
            } else {
                RetryDecision(sourceIndex, resumeFrom = 0, delayMs = backoff(attemptsOnSource))
            }

        // 有进展：原地续传能省流量也省时间
        is AttemptOutcome.Partial ->
            if (attemptsOnSource >= MAX_ATTEMPTS_PER_SOURCE) {
                switchSource(sourceIndex, sourceCount)
            } else {
                RetryDecision(sourceIndex, resumeFrom = outcome.bytesWritten, delayMs = backoff(attemptsOnSource))
            }

        // 换源重来：不能续一个已经确定是坏的文件
        is AttemptOutcome.Fatal -> switchSource(sourceIndex, sourceCount)
    }

    /**
     * 换源。**一律 `resumeFrom = 0`** —— 不做跨源续传。
     *
     * 理由：不同源上的 ETag 必然不同（CDN 与 GitHub 各有各的），`If-Range` 对不上；
     * 而且「把 A 源的前半截和 B 源的后半截拼起来」即使 sha256 能验出来，
     * 失败时也已经浪费了一整轮。APK 只有几 MB，重下的代价远小于正确性风险。
     */
    private fun switchSource(sourceIndex: Int, sourceCount: Int): RetryDecision =
        if (sourceIndex + 1 < sourceCount) {
            RetryDecision(nextSourceIndex = sourceIndex + 1, resumeFrom = 0, delayMs = 0)
        } else {
            RetryDecision(nextSourceIndex = null, resumeFrom = 0, delayMs = 0)
        }

    private fun backoff(attemptsOnSource: Int): Long =
        BACKOFF_MS.getOrElse(attemptsOnSource - 1) { BACKOFF_MS.last() }

    /**
     * 给定 release 的 tag，构造**候选下载源列表**（按「国内可达性」从好到坏排序）。
     *
     * ```
     * 1) cdn.lyb.pub            ← Cloudflare R2 镜像，国内最快，优先
     * 2) <serverUrl>/api/...    ← 自建 ethan 服务端，app 本来就连着它，几乎一定可达
     * 3) github.com/...         ← 永远存在，但在国内最差，放最后兜底
     * ```
     *
     * 顺序不是随便排的：`release-assets.githubusercontent.com` 的可达性差正是
     * 这次要解决的问题（见 PR 描述），所以它必须排在最后。
     *
     * 为什么要单独抽成纯函数：这段逻辑的失败模式是「组装出一个不存在的 URL，
     * 用户只看到『下载失败』」—— 极其难查。抽出来就能在 `commonTest` 里逐条断言。
     *
     * @param fallbackUrl GitHub 的 `browser_download_url`，一定不能丢。
     * @param serverUrl   用户配的服务器地址；未配置（空串 / null）时**跳过该源**，
     *                    不报错 —— 更新检查本身就是匿名可用的。
     * @return 去重且保序的列表；`fallbackUrl` 为空时可能是空列表。
     */
    fun candidateSources(tag: String, fallbackUrl: String, serverUrl: String? = null): List<String> {
        val key = tag.trim().trimStart('v').trim().takeIf { it.isNotEmpty() }
        val fromServer = if (key == null) {
            null
        } else {
            serverUrl?.trim()?.trimEnd('/')?.takeIf { it.startsWith("http") }
                ?.let { "$it/api/releases/android/v$key/app-release.apk" }
        }
        val fromCdn = key?.let { "https://cdn.lyb.pub/ethan/releases/android/v$it/app-release.apk" }

        return listOfNotNull(fromCdn, fromServer, fallbackUrl.trim().takeIf { it.isNotEmpty() })
            .distinct()
    }

    /**
     * HTTP 状态码 → 这次尝试算什么结果。
     *
     * @param bytesWritten 本次尝试后**落盘的累计字节数**（续传时含之前的部分）。
     * @param expectedTotal 远端文件总长；未知时传 0 或负数。
     * @param resumeWasRequested 本次是否带了 `Range` 头。**这个参数不能省**：
     *        同样是「200 但没下完」，含义完全不同 ——
     *        - 没带 Range（首次请求）：服务端只是把响应流截断了，磁盘上的
     *          这些字节是**正确文件的前缀**，要留着续传（`Partial`）；
     *        - 带了 Range：服务端**无视**了 Range 从头发，那磁盘上的是
     *          「我们以为是续传点、其实是别的段落」的数据，必须丢掉重来
     *          （`NeedsRestart`）。
     *
     *        把这两者混为一谈的后果：要么白扔已下载的几百 KB（每次都从头下，
     *        弱网下永远下不完），要么把两个不同段落拼在一起（校验失败）。
     */
    fun classifyCode(
        status: Int,
        bytesWritten: Long,
        expectedTotal: Long,
        resumeWasRequested: Boolean = false,
    ): AttemptOutcome = when {
        // 下完了：2xx 且长度对得上。expectedTotal 未知（<=0）时不能判定成功，
        // 交给调用方用 Content-Range / 校验去定，这里只算「有进展」。
        status in 200..299 && expectedTotal > 0 && bytesWritten >= expectedTotal ->
            AttemptOutcome.Success

        // 200 但没下完：带过 Range → 服务端无视了，已下载的字节作废；
        // 没带过 Range → 只是被截断，落盘的字节有效，留着续传。
        status == 200 ->
            if (resumeWasRequested) AttemptOutcome.NeedsRestart
            else AttemptOutcome.Partial(bytesWritten)

        // 206 部分内容，正常续传态
        status == 206 -> AttemptOutcome.Partial(bytesWritten)

        // Range 越界：本地记的偏移已经超过远端文件长度 → 远端文件换了
        status == 416 -> AttemptOutcome.NeedsRestart

        // 资源没了，重试没意义
        status == 404 || status == 410 -> AttemptOutcome.Fatal("HTTP $status")

        // 服务端/网关临时故障、限流、超时：值得重试
        status in 500..599 || status == 408 || status == 429 ->
            AttemptOutcome.Partial(bytesWritten)

        else -> AttemptOutcome.Fatal("HTTP $status")
    }
}
