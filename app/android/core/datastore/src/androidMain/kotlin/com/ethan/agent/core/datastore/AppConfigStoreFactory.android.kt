package com.ethan.agent.core.datastore

import android.content.Context

/**
 * Android 侧构造 [AppConfigStore]：把 DataStore 文件放在 app filesDir/datastore 下，
 * 文件名沿用旧的 preferencesDataStore(name = "ethan_prefs") 生成的 `ethan_prefs.preferences_pb`，
 * 保证已安装用户的存量配置不丢。
 */
fun AppConfigStore(context: Context): AppConfigStore {
    val path = context.filesDir.resolve("datastore/$APP_CONFIG_STORE_FILE").absolutePath
    return AppConfigStore(createAppConfigDataStore(path))
}
