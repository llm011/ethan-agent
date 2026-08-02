plugins {
    alias(libs.plugins.kotlin.multiplatform)
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    androidTarget {
        compilations.all {
            kotlinOptions {
                jvmTarget = "17"
            }
        }
    }

    // iOS targets: 真机 (arm64) + 模拟器 (x64 / arm64)
    iosX64()
    iosArm64()
    iosSimulatorArm64()

    sourceSets {
        commonMain.dependencies {
            implementation(project(":core:model"))
            implementation(project(":core:network"))
            implementation(project(":core:datastore"))
            implementation(libs.kotlinx.coroutines.core)
            implementation(libs.kotlinx.serialization.json)
            implementation(libs.okio)
            implementation(libs.koin.core)
            implementation(libs.koin.core.viewmodel)
            implementation(libs.androidx.lifecycle.viewmodel)
            implementation(libs.kotlinx.datetime)
        }

        androidMain.dependencies {
            implementation(libs.koin.android)
        }
    }
}

android {
    namespace = "com.ethan.agent.shared"
    compileSdk = 35

    defaultConfig {
        minSdk = 26
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
