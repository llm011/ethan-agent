package com.ethan.agent.ui.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp

@Composable
fun LoginScreen(
    state: AuthUiState,
    onLogin: (token: String, serverUrl: String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var token by remember { mutableStateOf("") }
    var serverUrl by remember { mutableStateOf(state.config.serverUrl) }
    var showToken by remember { mutableStateOf(false) }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("Ethan", style = MaterialTheme.typography.headlineLarge, color = MaterialTheme.colorScheme.primary)
        Text("你的个人 AI Agent", style = MaterialTheme.typography.bodyLarge)
        Spacer(Modifier.height(32.dp))

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("连接配置", style = MaterialTheme.typography.titleMedium)
                OutlinedTextField(
                    value = serverUrl,
                    onValueChange = { serverUrl = it },
                    label = { Text("服务器地址") },
                    placeholder = { Text("https://chat.lkfhome.cn:29999") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                )
                state.serverVersion?.let {
                    Text("服务端版本: $it", style = MaterialTheme.typography.bodySmall)
                }

                Spacer(Modifier.height(8.dp))
                Text("身份验证", style = MaterialTheme.typography.titleMedium)
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    label = { Text("Access Token") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        IconButton(onClick = { showToken = !showToken }) {
                            Icon(
                                if (showToken) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                contentDescription = null,
                            )
                        }
                    },
                )

                state.error?.let {
                    Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }

                Button(
                    onClick = { onLogin(token, serverUrl) },
                    enabled = !state.isLoading && token.isNotBlank() && serverUrl.isNotBlank(),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    if (state.isLoading) {
                        CircularProgressIndicator(modifier = Modifier.height(20.dp))
                    } else {
                        Text("登录")
                    }
                }
            }
        }

        Spacer(Modifier.height(16.dp))
        Text(
            "Token 对应服务端 config.yaml 中的 network.auth_token",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
