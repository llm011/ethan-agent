package com.ethan.agent.shared.update

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * [DownloadPlan] 的决策语义单测。
 *
 * 这些用例钉住的是「下载失败后到底该怎么走」—— 这是整个加固里最容易写错的部分，
 * 而且线上表现是「用户点了更新没反应」，很难复现。纯函数 + 全分支覆盖。
 */
class DownloadPlanTest {

    private val THREE_SOURCES = 3

    private fun next(
        sourceIndex: Int = 0,
        attempts: Int = 1,
        sourceCount: Int = THREE_SOURCES,
        outcome: AttemptOutcome,
    ) = DownloadPlan.next(sourceIndex, attempts, sourceCount, outcome)

    // ── Success ──────────────────────────────────────────────────────────────

    @Test
    fun `成功时不再安排任何动作`() {
        val d = next(outcome = AttemptOutcome.Success)
        assertNull(d.nextSourceIndex, "成功后不该再有下一个源")
        assertEquals(0, d.resumeFrom)
        assertEquals(0, d.delayMs, "成功后不该再等待")
    }

    // ── NeedsRestart：服务端不支持续传 / 远端文件变了 ─────────────────────────

    @Test
    fun `服务端忽略 Range 时_同源从头重试并退避`() {
        val d = next(attempts = 1, outcome = AttemptOutcome.NeedsRestart)
        assertEquals(0, d.nextSourceIndex, "还没到上限，留在这个源")
        assertEquals(0, d.resumeFrom, "必须从头，不能续")
        assertEquals(1_000, d.delayMs, "第一次失败退避 1s")
    }

    @Test
    fun `NeedsRestart 退避递增`() {
        assertEquals(1_000, next(attempts = 1, outcome = AttemptOutcome.NeedsRestart).delayMs)
        assertEquals(3_000, next(attempts = 2, outcome = AttemptOutcome.NeedsRestart).delayMs)
        // 第 3 次已到上限：不再退避等待，直接换源
        val atLimit = next(attempts = 3, outcome = AttemptOutcome.NeedsRestart)
        assertEquals(1, atLimit.nextSourceIndex)
        assertEquals(0, atLimit.delayMs)
    }

    @Test
    fun `NeedsRestart 达上限后换源且从头`() {
        val d = next(sourceIndex = 0, attempts = DownloadPlan.MAX_ATTEMPTS_PER_SOURCE, outcome = AttemptOutcome.NeedsRestart)
        assertEquals(1, d.nextSourceIndex, "换到下一个源")
        assertEquals(0, d.resumeFrom, "换源必须从头")
        assertEquals(0, d.delayMs, "换源立刻试，不等")
    }

    @Test
    fun `最后一个源也失败时放弃`() {
        val d = next(sourceIndex = 2, attempts = DownloadPlan.MAX_ATTEMPTS_PER_SOURCE, outcome = AttemptOutcome.NeedsRestart)
        assertNull(d.nextSourceIndex, "没有更多源了，应放弃")
    }

    // ── Partial：有进展 → 原地续传 ───────────────────────────────────────────

    @Test
    fun `下到一半时同源原地续传`() {
        val d = next(attempts = 1, outcome = AttemptOutcome.Partial(bytesWritten = 1_200_000))
        assertEquals(0, d.nextSourceIndex, "留在当前源续传")
        assertEquals(1_200_000, d.resumeFrom, "从已落盘的偏移继续")
    }

    @Test
    fun `续传也退避_避免打拥塞的链路`() {
        val d = next(attempts = 2, outcome = AttemptOutcome.Partial(bytesWritten = 500))
        assertEquals(3_000, d.delayMs)
    }

    @Test
    fun `Partial 达上限后换源且丢弃已下载字节`() {
        val d = next(
            sourceIndex = 1,
            attempts = DownloadPlan.MAX_ATTEMPTS_PER_SOURCE,
            outcome = AttemptOutcome.Partial(bytesWritten = 2_000_000),
        )
        assertEquals(2, d.nextSourceIndex)
        assertEquals(0, d.resumeFrom, "换源不续传：不能把两个源拼起来")
    }

    // ── Fatal：直接换源 ──────────────────────────────────────────────────────

    @Test
    fun `致命错误立刻换源_不等重试上限`() {
        val d = next(sourceIndex = 0, attempts = 1, outcome = AttemptOutcome.Fatal("HTTP 404"))
        assertEquals(1, d.nextSourceIndex, "第一次就换源，不该在本源耗到上限")
        assertEquals(0, d.resumeFrom, "坏文件不能续")
        assertEquals(0, d.delayMs)
    }

    @Test
    fun `末源致命错误时放弃`() {
        val d = next(sourceIndex = 2, attempts = 1, outcome = AttemptOutcome.Fatal("HTTP 410"))
        assertNull(d.nextSourceIndex)
    }

    @Test
    fun `单源场景下失败即放弃_不越界`() {
        val d = next(sourceIndex = 0, attempts = 1, sourceCount = 1, outcome = AttemptOutcome.Fatal("HTTP 404"))
        assertNull(d.nextSourceIndex, "只有一个源时不能指向越界下标")
    }

    // ── classifyCode ────────────────────────────────────────────────────────

    @Test
    fun `200 且长度达标算成功`() {
        assertEquals(
            AttemptOutcome.Success,
            DownloadPlan.classifyCode(status = 200, bytesWritten = 3_507_071, expectedTotal = 3_507_071),
        )
    }

    @Test
    fun `服务端无视 Range 时算需要重来`() {
        // 我们本地已有 1000 字节并请求续传（带 Range），服务端却从头发了一段就断 ——
        // 磁盘上那截数据的来历不可信，必须丢掉从头来。
        assertEquals(
            AttemptOutcome.NeedsRestart,
            DownloadPlan.classifyCode(
                status = 200,
                bytesWritten = 1_000,
                expectedTotal = 3_507_071,
                resumeWasRequested = true,
            ),
        )
    }

    @Test
    fun `首次请求被截断时保留已下载字节`() {
        // 没带 Range，服务器只是中途断了 —— 磁盘上的是正确文件的前缀，
        // 续传而不是重下。弱网下这条路径决定「能不能下完」。
        assertEquals(
            AttemptOutcome.Partial(1_000),
            DownloadPlan.classifyCode(status = 200, bytesWritten = 1_000, expectedTotal = 3_507_071),
        )
    }

    @Test
    fun `206 算部分内容_可续传`() {
        assertEquals(
            AttemptOutcome.Partial(1_500_000),
            DownloadPlan.classifyCode(status = 206, bytesWritten = 1_500_000, expectedTotal = 3_507_071),
        )
    }

    @Test
    fun `416 表示远端文件变了_必须从头`() {
        assertEquals(
            AttemptOutcome.NeedsRestart,
            DownloadPlan.classifyCode(status = 416, bytesWritten = 9_999_999, expectedTotal = 3_507_071),
        )
    }

    @Test
    fun `404 与 410 是致命_不该重试`() {
        assertEquals(AttemptOutcome.Fatal("HTTP 404"), DownloadPlan.classifyCode(404, 0, 3_507_071))
        assertEquals(AttemptOutcome.Fatal("HTTP 410"), DownloadPlan.classifyCode(410, 0, 3_507_071))
    }

    @Test
    fun `5xx 与 408 与 429 都值得重试`() {
        for (code in listOf(500, 502, 503, 504, 408, 429)) {
            assertEquals(
                AttemptOutcome.Partial(0),
                DownloadPlan.classifyCode(code, 0, 3_507_071),
                "HTTP $code 应该可重试",
            )
        }
    }

    @Test
    fun `总长未知时不能判成功_只能算有进展`() {
        // Content-Length / Content-Range 都拿不到（chunked）时，expectedTotal=0，
        // 不能让一次 2xx 就误判为「下完了」。
        val outcome = DownloadPlan.classifyCode(status = 200, bytesWritten = 4096, expectedTotal = 0)
        assertTrue(outcome !is AttemptOutcome.Success, "总长未知时绝不能判定成功")
        assertEquals(AttemptOutcome.Partial(4096), outcome, "应保留这 4096 字节并继续下")
    }

    @Test
    fun `其它 4xx 归为致命_不再空转重试`() {
        assertEquals(AttemptOutcome.Fatal("HTTP 403"), DownloadPlan.classifyCode(403, 0, 3_507_071))
    }

    @Test
    fun `被截断的 200 不能算成功_否则会把已下载的字节扔掉`() {
        // 回归：服务端把 200 响应发到一半就断，它的 Content-Length 就是那一小段。
        // 如果拿响应头当总长，会误判「下完了」→ 校验失败 → 删掉已下的 30 万字节
        // 从头再来。实机上这条路径表现为「每次都卡在同一个地方重来」。
        //
        // 修法是让调用方传元数据里的真实总长（3_507_071），
        // 于是这里正确落回 Partial —— 已下载的字节保住，下次原地续传。
        val outcome = DownloadPlan.classifyCode(status = 200, bytesWritten = 300_000, expectedTotal = 3_507_071)
        assertEquals(
            AttemptOutcome.Partial(300_000),
            outcome,
            "截断的 200 必须判为 Partial（可续传），不能是 Success",
        )
        assertTrue(outcome !is AttemptOutcome.Success)
    }

    @Test
    fun `200 的含义取决于这次有没有带 Range`() {
        // 同为「200 且没下完」，但磁盘上那截字节的来历不同：
        // - 没带 Range：服务器把首次响应截断了 → 是正确文件的前缀，留着续传
        // - 带了 Range：服务器无视 Range 从头发 → 来历不明，必须丢掉重来
        assertEquals(
            AttemptOutcome.Partial(300_000),
            DownloadPlan.classifyCode(200, 300_000, 3_507_071, resumeWasRequested = false),
        )
        assertEquals(
            AttemptOutcome.NeedsRestart,
            DownloadPlan.classifyCode(200, 300_000, 3_507_071, resumeWasRequested = true),
        )
    }

    // ── candidateSources ────────────────────────────────────────────────────

    private val GITHUB = "https://github.com/llm011/ethan-agent/releases/download/v0.5.259/app-release.apk"

    @Test
    fun `三个源按可达性排序_CDN 在前_GitHub 兜底`() {
        val sources = DownloadPlan.candidateSources(
            tag = "v0.5.259",
            fallbackUrl = GITHUB,
            serverUrl = "https://chat.example.com",
        )
        assertEquals(
            listOf(
                "https://cdn.lyb.pub/ethan/releases/android/v0.5.259/app-release.apk",
                "https://chat.example.com/api/releases/android/v0.5.259/app-release.apk",
                GITHUB,
            ),
            sources,
        )
    }

    @Test
    fun `没配服务器时跳过自建源_但 CDN 与 GitHub 仍在`() {
        // 更新检查是匿名可用的，serverUrl 为空只是少一个源，不能报错、不能少别的源
        val sources = DownloadPlan.candidateSources(tag = "v0.5.259", fallbackUrl = GITHUB, serverUrl = "")
        assertEquals(2, sources.size, "应为 CDN + GitHub 两条：$sources")
        assertEquals(GITHUB, sources.last(), "GitHub 必须是兜底的最后一条")
    }

    @Test
    fun `serverUrl 末尾斜杠不会拼出双斜杠`() {
        val sources = DownloadPlan.candidateSources("v0.5.259", GITHUB, "https://chat.example.com/")
        assertEquals(
            "https://chat.example.com/api/releases/android/v0.5.259/app-release.apk",
            sources[1],
        )
    }

    @Test
    fun `serverUrl 带路径时只取 origin 之外的部分照拼`() {
        // AppConfigStore 存的已经是 origin（ServerUrlUtils.normalize），这里只验证不崩
        val sources = DownloadPlan.candidateSources("v0.5.259", GITHUB, "https://chat.example.com:8443")
        assertEquals("https://chat.example.com:8443/api/releases/android/v0.5.259/app-release.apk", sources[1])
    }

    @Test
    fun `tag 里的 v 前缀不会拼成 vv`() {
        val sources = DownloadPlan.candidateSources("v0.5.259", GITHUB, null)
        assertEquals("https://cdn.lyb.pub/ethan/releases/android/v0.5.259/app-release.apk", sources[0])
        assertTrue(sources.none { it.contains("/vv") }, "拼出了 vv：$sources")
    }

    @Test
    fun `tag 不带 v 前缀时也能拼对`() {
        val sources = DownloadPlan.candidateSources("0.5.259", GITHUB, null)
        assertEquals("https://cdn.lyb.pub/ethan/releases/android/v0.5.259/app-release.apk", sources[0])
    }

    @Test
    fun `没有 tag 时只剩 GitHub 兜底`() {
        // tag 解析不出来（release 格式意外）时，绝不能拿空 tag 去拼一个必然 404 的 URL ——
        // 还要能靠 browser_download_url 正常更新
        val sources = DownloadPlan.candidateSources(tag = "", fallbackUrl = GITHUB, serverUrl = "https://a.com")
        assertEquals(listOf(GITHUB), sources)
    }

    @Test
    fun `源列表去重`() {
        // 万一 GitHub 的 download_url 恰好就是 CDN 地址
        val cdn = "https://cdn.lyb.pub/ethan/releases/android/v0.5.259/app-release.apk"
        assertEquals(listOf(cdn), DownloadPlan.candidateSources("v0.5.259", cdn, null))
    }

    @Test
    fun `fallbackUrl 为空且无 tag 时返回空列表_不抛异常`() {
        assertEquals(emptyList(), DownloadPlan.candidateSources(tag = "", fallbackUrl = "", serverUrl = null))
    }
}
