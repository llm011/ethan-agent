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
    val themeId: String = "honey",
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
            themeId = prefs[Keys.THEME_ID] ?: "honey",
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
}
