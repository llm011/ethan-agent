package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// ── Tool Tiers ────────────────────────────────────────────────────────────────

@Serializable
data class ToolInfoDto(
    val name: String = "",
    val description: String = "",
    @SerialName("fast_path") val fastPath: Boolean = false,
    @SerialName("in_full_base") val inFullBase: Boolean = false,
    @SerialName("side_effect") val sideEffect: Boolean = false,
    @SerialName("no_compress") val noCompress: Boolean = false,
)

@Serializable
data class TierDto(
    val key: String = "",
    val label: String = "",
    val desc: String = "",
    val tools: List<ToolInfoDto> = emptyList(),
)

@Serializable
data class ToolTiersResponse(
    val tiers: List<TierDto> = emptyList(),
    @SerialName("fast_count") val fastCount: Int = 0,
    @SerialName("fast_rule_tool_count") val fastRuleToolCount: Int = 0,
    @SerialName("full_count") val fullCount: Int = 0,
    @SerialName("longtail_count") val longtailCount: Int = 0,
    @SerialName("total_count") val totalCount: Int = 0,
)

// ── Fast Rules ────────────────────────────────────────────────────────────────

@Serializable
data class FastRuleDto(
    val name: String = "",
    val keywords: List<String> = emptyList(),
    val tools: List<String> = emptyList(),
    val skills: List<String> = emptyList(),
)

@Serializable
data class FastRulesResponse(
    @SerialName("fast_base_tools") val fastBaseTools: List<String> = emptyList(),
    @SerialName("fast_rules") val fastRules: List<FastRuleDto> = emptyList(),
)

@Serializable
data class NameDescDto(
    val name: String = "",
    val description: String = "",
)

@Serializable
data class FastRuleOptionsResponse(
    val tools: List<NameDescDto> = emptyList(),
    val skills: List<NameDescDto> = emptyList(),
)

@Serializable
data class FastRulePatch(
    val name: String = "",
    val keywords: List<String> = emptyList(),
    val tools: List<String> = emptyList(),
    val skills: List<String> = emptyList(),
)

@Serializable
data class FastRulesPatch(
    @SerialName("fast_base_tools") val fastBaseTools: List<String>? = null,
    @SerialName("fast_rules") val fastRules: List<FastRulePatch>? = null,
)

// ── Knowledge Validate ────────────────────────────────────────────────────────

@Serializable
data class KnowledgeValidateRequest(
    val backend: String = "filesystem",
    @SerialName("obsidian_vault_path") val obsidianVaultPath: String = "",
    @SerialName("obsidian_folder") val obsidianFolder: String = ".",
    @SerialName("external_base_url") val externalBaseUrl: String = "",
    @SerialName("external_api_key") val externalApiKey: String = "",
)

@Serializable
data class KnowledgeValidateResponse(
    val ok: Boolean = false,
    val message: String = "",
)

// ── Lark Deps ─────────────────────────────────────────────────────────────────

@Serializable
data class LarkDepsStatus(
    @SerialName("lark_oapi_installed") val larkOapiInstalled: Boolean = false,
    @SerialName("lark_cli_installed") val larkCliInstalled: Boolean = false,
    @SerialName("lark_cli_app_synced") val larkCliAppSynced: Boolean = false,
    @SerialName("lark_cli_app_matches") val larkCliAppMatches: Boolean = false,
    val installing: Boolean = false,
    @SerialName("last_error") val lastError: String = "",
    @SerialName("last_run_at") val lastRunAt: String = "",
    @SerialName("installed_by") val installedBy: String = "",
)
