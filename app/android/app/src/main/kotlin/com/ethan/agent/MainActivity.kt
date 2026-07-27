package com.ethan.agent

import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.hilt.navigation.compose.hiltViewModel
import com.ethan.agent.ui.EthanApp
import com.ethan.agent.ui.auth.AuthViewModel
import com.ethan.agent.ui.theme.EthanTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    // Shared content received via ACTION_SEND (Share to Ethan)
    var pendingShareText: String? = null
    var pendingShareUri: android.net.Uri? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handleShareIntent(intent)
        setContent {
            val authViewModel: AuthViewModel = hiltViewModel()
            // EthanTheme reads ThemeState.themeId set by SettingsViewModel.setTheme()
            EthanTheme {
                EthanApp(authViewModel = authViewModel)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleShareIntent(intent)
    }

    private fun handleShareIntent(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND) return
        when {
            intent.type?.startsWith("text/") == true -> {
                pendingShareText = intent.getStringExtra(Intent.EXTRA_TEXT)
            }
            intent.type?.startsWith("image/") == true ||
            intent.type?.startsWith("application/") == true -> {
                pendingShareUri = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(Intent.EXTRA_STREAM, android.net.Uri::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra<android.net.Uri>(Intent.EXTRA_STREAM)
                }
            }
        }
    }
}
