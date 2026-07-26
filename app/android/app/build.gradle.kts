import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.hilt)
    alias(libs.plugins.ksp)
}

// 读取本地 ~/.gradle/gradle.properties 中的签名信息（CI 通过环境变量注入）
fun loadSigningProps(): Properties? {
    val props = Properties()
    // 优先用环境变量
    val envStore = System.getenv("ANDROID_STORE_FILE")
    if (!envStore.isNullOrBlank()) {
        props["ANDROID_STORE_FILE"] = envStore
        props["ANDROID_STORE_PASSWORD"] = System.getenv("ANDROID_STORE_PASSWORD") ?: ""
        props["ANDROID_KEY_ALIAS"] = System.getenv("ANDROID_KEY_ALIAS") ?: ""
        props["ANDROID_KEY_PASSWORD"] = System.getenv("ANDROID_KEY_PASSWORD") ?: ""
        return props
    }
    // 否则读 ~/.gradle/gradle.properties
    val gradleHome = System.getProperty("user.home") ?: return null
    val file = java.io.File(gradleHome, ".gradle/gradle.properties")
    if (!file.exists()) return null
    file.inputStream().use { props.load(it) }
    if (props.getProperty("ANDROID_STORE_FILE") == null) return null
    return props
}

android {
    namespace = "com.ethan.agent"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.ethan.agent"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"

        vectorDrawables {
            useSupportLibrary = true
        }
    }

    signingConfigs {
        create("release") {
            val props = loadSigningProps()
            if (props != null) {
                storeFile = java.io.File(props.getProperty("ANDROID_STORE_FILE"))
                storePassword = props.getProperty("ANDROID_STORE_PASSWORD")
                keyAlias = props.getProperty("ANDROID_KEY_ALIAS")
                keyPassword = props.getProperty("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            // 仅当签名信息可用时才挂 signingConfig，否则用默认 debug key 出包（CI 无签名环境时也能跑通）
            val props = loadSigningProps()
            if (props != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(project(":core:model"))
    implementation(project(":core:network"))
    implementation(project(":core:datastore"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons)
    implementation(libs.androidx.navigation.compose)

    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.hilt.navigation.compose)

    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.compose.markdown)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.retrofit)

    debugImplementation(libs.androidx.compose.ui.tooling)
}
