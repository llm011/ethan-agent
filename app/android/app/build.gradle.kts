import java.io.File
import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.hilt)
    alias(libs.plugins.ksp)
}

// 从仓库根 pyproject.toml 读取版本号，与 release tag 保持同步
// （pyproject.toml 是唯一版本源，auto-bump 只 bump 它；
//  Android / desktop 构建时各自从此读取，不再依赖 sed 同步）
fun readPyprojectVersion(): String {
    val pyproject = File(rootProject.projectDir.parentFile.parentFile, "pyproject.toml")
    if (!pyproject.exists()) return "0.0.1"
    val match = Regex("""^version\s*=\s*"([^"]+)"""", RegexOption.MULTILINE)
        .find(pyproject.readText())
    return match?.groupValues?.get(1) ?: "0.0.1"
}

// versionCode 必须是整数且单调递增，从语义版本派生：major*1000000 + minor*1000 + patch
fun deriveVersionCode(version: String): Int {
    val parts = version.split("-")[0].split(".").map { it.toIntOrNull() ?: 0 }
    val major = parts.getOrElse(0) { 0 }
    val minor = parts.getOrElse(1) { 0 }
    val patch = parts.getOrElse(2) { 0 }
    return major * 1_000_000 + minor * 1_000 + patch
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
    val file = File(gradleHome, ".gradle/gradle.properties")
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
        val appVersion = readPyprojectVersion()
        versionCode = deriveVersionCode(appVersion)
        versionName = appVersion

        vectorDrawables {
            useSupportLibrary = true
        }
    }

    signingConfigs {
        create("release") {
            val props = loadSigningProps()
            if (props != null) {
                storeFile = File(props.getProperty("ANDROID_STORE_FILE"))
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
            // 有正式签名就用正式的，否则回退 debug 签名（保证 release 包一定能装）
            val props = loadSigningProps()
            signingConfig = if (props != null) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
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
    implementation(libs.androidx.lifecycle.process)
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
    implementation(libs.okhttp) // AppUpdater 仍直接用 OkHttp 下载 APK
    implementation(libs.coil.compose)
    implementation(libs.androidx.biometric)
    implementation(libs.material3.window.size)

    debugImplementation(libs.androidx.compose.ui.tooling)
}
