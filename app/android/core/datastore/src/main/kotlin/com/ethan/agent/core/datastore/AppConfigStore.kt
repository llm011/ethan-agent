package com.ethan.agent.core.datastore

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.ethan.agent.core.model.ServerUrlUtils
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.first

const val DEFAULT_SERVER_URL = ServerUrlUtils.DEFAULT_SERVER_URL

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "ethan_prefs")

data class AppConfig(
    val serverUrl: String = DEFAULT_SERVER_URL,
    val authToken: String = "",
    val darkTheme: Boolean? = null,
    val userId: String? = null,
    val userName: String? = null,
    val isAdmin: Boolean = false,
) {
    val apiBaseUrl: String
        get() = ServerUrlUtils.toApiBaseUrl(serverUrl)

    val isConfigured: Boolean
        get() = serverUrl.isNotBlank() && authToken.isNotBlank()
}

class AppConfigStore(
    private val context: Context,
) {
    private object Keys {
        val SERVER_URL = stringPreferencesKey("server_url")
        val AUTH_TOKEN = stringPreferencesKey("auth_token")
        val DARK_THEME = booleanPreferencesKey("dark_theme")
        val USER_ID = stringPreferencesKey("user_id")
        val USER_NAME = stringPreferencesKey("user_name")
        val IS_ADMIN = booleanPreferencesKey("is_admin")
    }

    val config: Flow<AppConfig> = context.dataStore.data.map { prefs ->
        val rawUrl = prefs[Keys.SERVER_URL]
        val serverUrl = rawUrl?.let { ServerUrlUtils.normalize(it) } ?: DEFAULT_SERVER_URL
        AppConfig(
            serverUrl = serverUrl,
            authToken = prefs[Keys.AUTH_TOKEN] ?: "",
            darkTheme = prefs[Keys.DARK_THEME],
            userId = prefs[Keys.USER_ID],
            userName = prefs[Keys.USER_NAME],
            isAdmin = prefs[Keys.IS_ADMIN] ?: false,
        )
    }

    suspend fun saveServerUrl(url: String) {
        val normalized = ServerUrlUtils.normalize(url) ?: url.trim().trimEnd('/')
        context.dataStore.edit { it[Keys.SERVER_URL] = normalized }
    }

    suspend fun saveAuth(token: String, userId: String?, userName: String?, isAdmin: Boolean) {
        context.dataStore.edit {
            it[Keys.AUTH_TOKEN] = token
            if (userId != null) it[Keys.USER_ID] = userId else it.remove(Keys.USER_ID)
            if (userName != null) it[Keys.USER_NAME] = userName else it.remove(Keys.USER_NAME)
            it[Keys.IS_ADMIN] = isAdmin
        }
    }

    suspend fun clearAuth() {
        context.dataStore.edit {
            it.remove(Keys.AUTH_TOKEN)
            it.remove(Keys.USER_ID)
            it.remove(Keys.USER_NAME)
            it.remove(Keys.IS_ADMIN)
        }
    }

    suspend fun repairStoredUrlIfNeeded() {
        val prefs = context.dataStore.data.first()
        val raw = prefs[Keys.SERVER_URL] ?: return
        val fixed = ServerUrlUtils.normalize(raw) ?: return
        if (fixed != raw) {
            context.dataStore.edit { it[Keys.SERVER_URL] = fixed }
        }
    }

    suspend fun setDarkTheme(dark: Boolean) {
        context.dataStore.edit { it[Keys.DARK_THEME] = dark }
    }
}
