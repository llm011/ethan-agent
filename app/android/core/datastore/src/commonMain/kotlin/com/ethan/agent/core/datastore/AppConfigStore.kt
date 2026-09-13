package com.ethan.agent.core.datastore

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import com.ethan.agent.core.model.ServerUrlUtils
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import okio.Path.Companion.toPath

const val DEFAULT_SERVER_URL = ServerUrlUtils.DEFAULT_SERVER_URL

/** DataStore 文件名（各平台各自决定放在哪个目录，文件名保持一致）。 */
const val APP_CONFIG_STORE_FILE = "ethan_prefs.preferences_pb"

/**
 * 用绝对路径创建 KMP Preferences DataStore。
 * 平台侧只需算出目标目录并拼上 [APP_CONFIG_STORE_FILE]，其余读写逻辑全共享。
 */
fun createAppConfigDataStore(absolutePath: String): DataStore<Preferences> =
    PreferenceDataStoreFactory.createWithPath(produceFile = { absolutePath.toPath() })

data class AppConfig(
    val serverUrl: String = DEFAULT_SERVER_URL,
    val authToken: String = "",
    val darkTheme: Boolean? = null,
    val userId: String? = null,
    val userName: String? = null,
    val isAdmin: Boolean = false,
    val themeId: String = "system",
    val appLockEnabled: Boolean = false,
    val autoConsentEnabled: Boolean = false,
) {
    val apiBaseUrl: String
        get() = ServerUrlUtils.toApiBaseUrl(serverUrl)

    val isConfigured: Boolean
        get() = serverUrl.isNotBlank() && authToken.isNotBlank()
}

/**
 * KMP 版配置存储：接收建好的 [DataStore]（平台侧决定路径），
 * 读写逻辑（含 URL 归一化、鉴权）全部在 commonMain 共享。
 */
class AppConfigStore(
    private val dataStore: DataStore<Preferences>,
) {
    private object Keys {
        val SERVER_URL = stringPreferencesKey("server_url")
        val AUTH_TOKEN = stringPreferencesKey("auth_token")
        val DARK_THEME = booleanPreferencesKey("dark_theme")
        val USER_ID = stringPreferencesKey("user_id")
        val USER_NAME = stringPreferencesKey("user_name")
        val IS_ADMIN = booleanPreferencesKey("is_admin")
        val THEME_ID = stringPreferencesKey("theme_id")
        val APP_LOCK = booleanPreferencesKey("app_lock_enabled")
        val AUTO_CONSENT = booleanPreferencesKey("auto_consent_enabled")

        /**
         * 每个会话的输入框草稿：`draft_<sessionId>` -> 草稿正文。
         *
         * 对齐 Web 的 `useInputStore`（`web/components/chat/use-input-store.ts`）：
         * 按 sessionId 缓存草稿，切会话时保存当前、恢复目标，重进 App 也还在
         * （Web 用 sessionStorage，这里用 DataStore 落在磁盘上，比 Web 还持久）。
         * 新建会话（sessionId 为空）用 [DRAFT_NEW] 这个哨兵 key —— 用户还没发消息
         * 时后端没有 sessionId，草稿也得有地方存。
         */
        const val DRAFT_PREFIX = "draft_"
        const val DRAFT_NEW = "draft_@new"
    }

    val config: Flow<AppConfig> = dataStore.data.map { prefs ->
        val rawUrl = prefs[Keys.SERVER_URL]
        val serverUrl = rawUrl?.let { ServerUrlUtils.normalize(it) } ?: DEFAULT_SERVER_URL
        AppConfig(
            serverUrl = serverUrl,
            authToken = prefs[Keys.AUTH_TOKEN] ?: "",
            darkTheme = prefs[Keys.DARK_THEME],
            userId = prefs[Keys.USER_ID],
            userName = prefs[Keys.USER_NAME],
            isAdmin = prefs[Keys.IS_ADMIN] ?: false,
            themeId = prefs[Keys.THEME_ID] ?: "system",
            appLockEnabled = prefs[Keys.APP_LOCK] ?: false,
            autoConsentEnabled = prefs[Keys.AUTO_CONSENT] ?: false,
        )
    }

    suspend fun saveServerUrl(url: String) {
        val normalized = ServerUrlUtils.normalize(url) ?: url.trim().trimEnd('/')
        dataStore.edit { it[Keys.SERVER_URL] = normalized }
    }

    suspend fun saveAuth(token: String, userId: String?, userName: String?, isAdmin: Boolean) {
        dataStore.edit {
            it[Keys.AUTH_TOKEN] = token
            if (userId != null) it[Keys.USER_ID] = userId else it.remove(Keys.USER_ID)
            if (userName != null) it[Keys.USER_NAME] = userName else it.remove(Keys.USER_NAME)
            it[Keys.IS_ADMIN] = isAdmin
        }
    }

    suspend fun clearAuth() {
        dataStore.edit {
            it.remove(Keys.AUTH_TOKEN)
            it.remove(Keys.USER_ID)
            it.remove(Keys.USER_NAME)
            it.remove(Keys.IS_ADMIN)
        }
    }

    suspend fun repairStoredUrlIfNeeded() {
        val prefs = dataStore.data.first()
        val raw = prefs[Keys.SERVER_URL] ?: return
        val fixed = ServerUrlUtils.normalize(raw) ?: return
        if (fixed != raw) {
            dataStore.edit { it[Keys.SERVER_URL] = fixed }
        }
    }

    suspend fun setDarkTheme(dark: Boolean) {
        dataStore.edit { it[Keys.DARK_THEME] = dark }
    }

    suspend fun setThemeId(themeId: String) {
        dataStore.edit { it[Keys.THEME_ID] = themeId }
    }

    suspend fun setAppLockEnabled(enabled: Boolean) {
        dataStore.edit { it[Keys.APP_LOCK] = enabled }
    }

    suspend fun setAutoConsentEnabled(enabled: Boolean) {
        dataStore.edit { it[Keys.AUTO_CONSENT] = enabled }
    }

    // ── 输入框草稿（按会话） ────────────────────────────────────────────

    /** 草稿 key：登录/登出等场景下会同时换用户，草稿不跨用户共享。 */
    private fun draftKey(sessionId: String?): Preferences.Key<String> =
        stringPreferencesKey(
            if (sessionId.isNullOrBlank()) Keys.DRAFT_NEW else Keys.DRAFT_PREFIX + sessionId,
        )

    /** 读某个会话的草稿（没有则空串）。 */
    suspend fun draft(sessionId: String?): String =
        dataStore.data.first()[draftKey(sessionId)] ?: ""

    /**
     * 写某个会话的草稿。**空草稿会直接删掉这个 key**，避免 DataStore 里
     * 攒下成百上千条空记录（每个聊过的会话都会留一条）。
     */
    suspend fun saveDraft(sessionId: String?, text: String) {
        val key = draftKey(sessionId)
        dataStore.edit { prefs ->
            if (text.isBlank()) prefs.remove(key) else prefs[key] = text
        }
    }
}
