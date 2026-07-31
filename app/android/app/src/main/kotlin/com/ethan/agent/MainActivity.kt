package com.ethan.agent

import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.fragment.app.FragmentActivity
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.lifecycle.lifecycleScope
import com.ethan.agent.auth.BiometricLockManager
import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.share.ShareBus
import com.ethan.agent.ui.EthanApp
import com.ethan.agent.ui.auth.AuthViewModel
import com.ethan.agent.ui.theme.EthanTheme
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : FragmentActivity() {

    @Inject
    lateinit var configStore: AppConfigStore

    /** 应用锁功能是否开启（异步读 config 后确定）。 */
    private var lockEnabled = false

    /** 当前是否处于锁定态。true=显示 LockGate，false=显示主界面。 */
    private val locked = mutableStateOf(false)

    /** 当前主题 id（持续跟随 config，Settings 里切换即时生效）。 */
    private val themeId = mutableStateOf("system")

    /** config 是否读取完成。未完成时显示 splash，避免开锁场景下主界面闪现。 */
    private val configLoaded = mutableStateOf(false)

    /**
     * 应用退到后台时重新加锁。用 ProcessLifecycleOwner 而非 Activity 生命周期：
     * BiometricPrompt 弹窗只会让 Activity onPause，不会触发进程级 ON_STOP，
     * 因此解锁过程本身不会误触发重新加锁。
     */
    private val processObserver = object : DefaultLifecycleObserver {
        override fun onStop(owner: LifecycleOwner) {
            if (lockEnabled) locked.value = true
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handleShareIntent(intent)

        ProcessLifecycleOwner.get().lifecycle.addObserver(processObserver)

        // 异步读应用锁开关，避免在主线程 runBlocking 阻塞（ANR 反模式）。
        // 读完成前 configLoaded=false，界面显示 splash，开锁时不会闪现主界面。
        // 仅在首次读取时决定初始锁定态；主题则持续跟随 config，Settings 切换即时生效。
        lifecycleScope.launch {
            var firstEmit = true
            configStore.config.collect { config ->
                themeId.value = config.themeId
                // lockEnabled 持续跟随开关（用户在设置里开/关后，退后台重新加锁的判断能即时生效）
                lockEnabled = config.appLockEnabled
                if (firstEmit) {
                    // 仅首次读取时决定初始锁定态，避免后续 config 变更把已解锁界面又锁上
                    locked.value = lockEnabled
                    configLoaded.value = true
                    firstEmit = false
                }
            }
        }

        setContent {
            val authViewModel: AuthViewModel = hiltViewModel()
            EthanTheme(themeId = themeId.value) {
                when {
                    !configLoaded.value -> SplashGate()
                    locked.value -> LockGate(onUnlock = { locked.value = false })
                    else -> EthanApp(authViewModel = authViewModel)
                }
            }
        }
    }

    override fun onDestroy() {
        ProcessLifecycleOwner.get().lifecycle.removeObserver(processObserver)
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleShareIntent(intent)
    }

    /** 把 ACTION_SEND 内容投递到 ShareBus，由 ChatViewModel 消费。 */
    private fun handleShareIntent(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND) return
        when {
            intent.type?.startsWith("text/") == true -> {
                ShareBus.postText(intent.getStringExtra(Intent.EXTRA_TEXT))
            }
            intent.type?.startsWith("image/") == true ||
                intent.type?.startsWith("application/") == true -> {
                val uri = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(Intent.EXTRA_STREAM, android.net.Uri::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra<android.net.Uri>(Intent.EXTRA_STREAM)
                }
                ShareBus.postUri(uri?.toString())
            }
        }
    }

    /** config 读取期间的占位遮罩，避免开锁场景下主界面短暂闪现。 */
    @Composable
    private fun SplashGate() {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {}
    }

    /** 应用锁遮罩：验证通过前不渲染主界面内容。 */
    @Composable
    private fun LockGate(onUnlock: () -> Unit) {
        // 进入即自动弹一次系统验证
        LaunchedEffect(Unit) {
            promptUnlock(onUnlock)
        }
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            Column(
                modifier = Modifier.fillMaxSize().padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Text("Ethan 已锁定", style = MaterialTheme.typography.titleLarge)
                Text(
                    "请通过生物识别或设备密码解锁",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp, bottom = 24.dp),
                )
                Button(onClick = { promptUnlock(onUnlock) }) { Text("解锁") }
            }
        }
    }

    private fun promptUnlock(onUnlock: () -> Unit) {
        BiometricLockManager.authenticate(
            activity = this,
            onSuccess = onUnlock,
            onFailure = { /* 保持锁定，用户可点「解锁」重试 */ },
        )
    }
}
