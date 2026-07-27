# Add project specific ProGuard rules here.

# ===== Kotlin / Coroutines =====
-keepclassmembers class kotlin.coroutines.jvm.internal.BaseContinuationImpl { *; }
-dontwarn kotlinx.coroutines.**

# ===== Hilt / Dagger 2 =====
# Hilt 生成的代码需要保留，否则反射注入失败
-keep class dagger.hilt.** { *; }
-keep class * extends dagger.hilt.android.HiltAndroidApp { *; }
-keep @dagger.hilt.android.HiltAndroidApp class * { *; }
-keep @dagger.hilt.android.lifecycle.HiltViewModel class * { *; }
-keepclassmembers class * { @javax.inject.Inject *; }
-keepclassmembers class * { @dagger.hilt.android.qualifiers.* *; }
# 防止被 @Inject 注入的类被裁剪
-keep,allowobfuscation,allowshrinking class kotlin.Metadata { *; }
# Hilt 的 BaseFragment / Activity 不能被裁剪
-keep class androidx.fragment.app.Fragment { *; }
-keep class androidx.activity.ComponentActivity { *; }

# ===== Retrofit 2 =====
# Retrofit 用反射构造 Service 接口的动态代理
-keepattributes RuntimeVisibleAnnotations, RuntimeVisibleParameterAnnotations
-keepclassmembers,allowshrinking,allowobfuscation interface * {
    @retrofit2.http.* <methods>;
}
-keep,allowobfuscation,allowshrinking class retrofit2.Response { *; }
-keep,allowobfuscation,allowshrinking class kotlin.coroutines.Continuation
# Retrofit 2.x 官方推荐规则
-dontwarn retrofit2.**
-dontwarn org.codehaus.mojo.animal_sniffer.IgnoreJRERequirement

# ===== OkHttp 3 / 4 =====
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn org.conscrypt.**
# PlatformName 走反射
-keepnames class okhttp3.internal.platform.Platform { *; }

# ===== kotlinx.serialization =====
# 序列化插件在编译期生成代码，但运行时通过 Serializer.lookup 仍可能反射 KSerializer
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
# 顶层 @Serializable 数据类（@SerialName 走生成的 serializer$，但保险起见 keep）
-keep,includedescriptorclasses class com.ethan.agent.core.model.**$$serializer { *; }
-keepclassmembers class com.ethan.agent.core.model.** {
    *** Companion;
}
-keepclasseswithmembers class com.ethan.agent.core.model.** {
    kotlinx.serialization.KSerializer serializer(...);
}
# Json 配置类
-keepclassmembers class kotlinx.serialization.json.Json { *; }

# ===== Compose =====
# Compose 用反射读取 Composable 函数信息（一般不会裁掉，但保险）
-dontwarn androidx.compose.**

# ===== 项目自身模型类（kotlinx.serialization 反序列化必需） =====
-keep class com.ethan.agent.core.model.** { *; }
