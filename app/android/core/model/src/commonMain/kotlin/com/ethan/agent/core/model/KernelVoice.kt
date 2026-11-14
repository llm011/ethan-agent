package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// ── AI 内核（多内核运行时）──────────────────────────────────────────────────
//
// 对应后端 `ethan/interface/routers/settings.py` 的 /api/kernels 系列。
//
// 关键语义：内核决定「由谁执行这一轮对话」。
//   · ethan        —— 原生，使用 Ethan 的全部能力
//   · 外部内核      —— 把执行权交给对应 CLI（Claude Code / DSH / Pi …）
//
// `sharesEthanTools` 是「内核作为 Ethan 的心脏」这一目标的核心指标：
// 能共享 → 它用 Ethan 的工具干活；不能共享 → 只是个外接的三方 agent。

@Serializable
data class KernelCapabilitiesDto(
    val streaming: Boolean = true,
    val tools: Boolean = true,
    /** 能否执行中途向用户请求授权。外部 runtime 多为 false（权限模型不同源）。 */
    val consent: Boolean = true,
    /** 是否沿用 Ethan 的技能/记忆/系统提示词。外部 runtime 为 false。 */
    @SerialName("ethan_context") val ethanContext: Boolean = true,
    val resumable: Boolean = false,
    /**
     * 能否共享 Ethan 的工具/技能（经 MCP 注入）。
     * 实测：ethan / dsh / claude_code 可用；codex / opencode / pi 不可用。
     */
    @SerialName("shares_ethan_tools") val sharesEthanTools: Boolean = false,
    /** 不能共享时的原因（可操作说明，不是「暂不支持」）。 */
    @SerialName("shares_ethan_tools_reason") val sharesEthanToolsReason: String = "",
)

@Serializable
data class KernelInfoDto(
    val kind: String = "",
    val name: String = "",
    val available: Boolean = false,
    /** 不可用原因（如「未安装 claude」） */
    val reason: String = "",
    val capabilities: KernelCapabilitiesDto = KernelCapabilitiesDto(),
    /** 一键安装命令（缺失依赖时展示给用户看） */
    @SerialName("install_command") val installCommand: String = "",
    @SerialName("install_hint") val installHint: String = "",
)

@Serializable
data class KernelsResponse(
    val kernels: List<KernelInfoDto> = emptyList(),
    /** 当前默认内核 kind */
    val default: String = "ethan",
    /** 按任务类型选内核的映射，如 {"coding": "claude_code"} */
    @SerialName("task_rules") val taskRules: Map<String, String> = emptyMap(),
)

@Serializable
data class KernelSelectRequest(
    val kind: String,
    /**
     * 依赖缺失时是否自动安装。默认 true —— 这就是「用户选了就装，不用手敲命令」。
     */
    @SerialName("auto_install") val autoInstall: Boolean = true,
)

@Serializable
data class KernelSelectResponse(
    val ok: Boolean = false,
    val default: String = "ethan",
)

// ── 语音后端（TTS / ASR）────────────────────────────────────────────────────
//
// 本地后端 ethan-tts 依赖 Apple Silicon + MLX，不是所有机器都能跑。
// 所以 UI 必须先看 available，不能假设「选了就能用」。

@Serializable
data class VoiceCheckDto(
    val name: String = "",
    /** ok | error | warn */
    val status: String = "ok",
    val detail: String = "",
    /** 修复建议（后端给的，通常是可执行的命令） */
    val fix: String = "",
)

@Serializable
data class VoiceBackendDto(
    val backend: String = "",
    val available: Boolean = false,
    val reason: String = "",
    @SerialName("cli_path") val cliPath: String = "",
    @SerialName("service_url") val serviceUrl: String = "",
    @SerialName("service_running") val serviceRunning: Boolean = false,
    val checks: List<VoiceCheckDto> = emptyList(),
)

@Serializable
data class VoicePlatformDto(
    val system: String = "",
    val machine: String = "",
    @SerialName("apple_silicon") val appleSilicon: Boolean = false,
)

@Serializable
data class VoiceBackendsResponse(
    /** key 为后端名：edge-tts / ethan-tts */
    val tts: Map<String, VoiceBackendDto> = emptyMap(),
    val asr: VoiceBackendDto = VoiceBackendDto(),
    val platform: VoicePlatformDto = VoicePlatformDto(),
    val python: String = "",
    /** 当前选中的后端 */
    val current: VoiceCurrentDto = VoiceCurrentDto(),
)

@Serializable
data class VoiceCurrentDto(
    val tts: String = "edge-tts",
    val asr: String = "off",
)

@Serializable
data class VoiceSelectRequest(
    val tts: String = "",
    val asr: String = "",
)

@Serializable
data class VoiceSelectResponse(
    val ok: Boolean = false,
    val tts: String = "",
    val asr: String = "",
)
