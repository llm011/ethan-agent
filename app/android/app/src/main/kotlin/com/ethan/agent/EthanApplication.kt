package com.ethan.agent

import android.app.Application
import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.data.AndroidAppUpdater
import com.ethan.agent.shared.AppUpdater
import com.ethan.agent.shared.appContext
import com.ethan.agent.shared.di.sharedModule
import org.koin.android.ext.koin.androidContext
import org.koin.core.context.startKoin
import org.koin.dsl.module

class EthanApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        appContext = this
        startKoin {
            androidContext(this@EthanApplication)
            modules(sharedModule(), platformModule())
        }
    }

    private fun platformModule() = module {
        single { AppConfigStore(androidContext()) }
        single<AppUpdater> { AndroidAppUpdater(androidContext()) }
    }
}
