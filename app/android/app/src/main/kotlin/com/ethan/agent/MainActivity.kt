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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.fragment.app.FragmentActivity
import androidx.hilt.navigation.compose.hiltViewModel
import com.ethan.agent.auth.BiometricLockManager
import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.share.ShareBus
import com.ethan.agent.ui.EthanApp
import com.ethan.agent.ui.auth.AuthViewModel
import com.ethan.agent.ui.theme.EthanTheme
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : FragmentActivity() {

    @Inject
    lateinit var configStore: AppConfigStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handleShareIntent(intent)

        // 冷启动时读一次应用锁开关（DataStore first() 极快，不会明显阻塞启动）
        val lockEnabled = runCatching {
            runBlocking { configStore.config.first().appLockEnabled }
        }.getOrDefault(false)

        setContent {
            val authViewModel: AuthViewModel = hiltViewModel()
            EthanTheme {
                // locked 初值：开启了应用锁则先锁住
                var locked by remember { mutableStateOf(lockEnabled) }

                if (locked) {
                    LockGate(
                        onUnlock = { locked = false },
                    )
                } else {
                    EthanApp(authViewModel = authViewModel)
                }
            }
        }
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

    /** 应用锁遮罩：验证通过前不渲染主界面内容。 */
    @androidx.compose.runtime.Composable
    private fun LockGate(onUnlock: () -> Unit) {
        // 进入即自动弹一次系统验证
        androidx.compose.runtime.LaunchedEffect(Unit) {
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
