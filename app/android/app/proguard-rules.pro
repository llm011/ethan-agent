# ChatRepository - Repository 层保留
-keep class com.ethan.agent.core.repository.** { *; }

# ViewModel - 保留所有字段和方法
-keep class com.ethan.agent.shared.viewmodel.** { *; }

# Model - 保留所有数据类
-keep class com.ethan.agent.core.model.** { *; }

# Koin DI - 保留依赖注入配置
-keepattributes RuntimeVisibleAnnotations
-keep class * extends org.koin.core.module.Module

# Compose - 保留 Composable 函数
-keepnames class * { @androidx.compose.runtime.Composable *; }

# Serialization - 保留序列化类
-keep class kotlinx.serialization.** { *; }
-keepclasseswithmembers class * {
    @kotlinx.serialization.SerialName <fields>;
}

# Network - OkHttp 相关
-keep class okhttp3.** { *; }
-keepclassmembers class okhttp3.** {
    public *;
}

# Coroutines - 协程相关
-keepnames class kotlinx.coroutines.internal.MainDispatcherFactory {}
-keepnames class kotlinx.coroutines.CoroutineExceptionHandler {}
