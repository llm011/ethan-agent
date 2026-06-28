package com.ethan.agent

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.hilt.navigation.compose.hiltViewModel
import com.ethan.agent.ui.EthanApp
import com.ethan.agent.ui.auth.AuthViewModel
import com.ethan.agent.ui.theme.EthanTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val authViewModel: AuthViewModel = hiltViewModel()
            val authState by authViewModel.state.collectAsState()
            val systemDark = isSystemInDarkTheme()
            val darkTheme = authState.darkTheme ?: systemDark

            EthanTheme(darkTheme = darkTheme) {
                EthanApp(authViewModel = authViewModel)
            }
        }
    }
}
