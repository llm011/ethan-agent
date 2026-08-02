package com.ethan.agent

import android.app.Application
import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.data.AndroidAppUpdater
import com.ethan.agent.shared.AppUpdater
import com.ethan.agent.shared.appContext
import com.ethan.agent.shared.initKoin
import com.ethan.agent.shared.setupAndroidPlatformModule
import org.koin.android.ext.koin.androidContext
import org.koin.dsl.module

class EthanApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        appContext = this
        // platformModule 引用了 :app 的 AndroidAppUpdater（:shared 不能反向依赖 :app），
        // 所以在 :app 这边定义，通过 setupAndroidPlatformModule 注入给 shared 的 initKoin。
        setupAndroidPlatformModule {
            module {
                single { AppConfigStore(androidContext()) }
                single<AppUpdater> { AndroidAppUpdater(androidContext()) }
            }
        }
        initKoin()
    }
}
