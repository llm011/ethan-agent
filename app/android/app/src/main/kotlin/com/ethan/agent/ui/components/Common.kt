package com.ethan.agent.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.ToolStep

@Composable
fun LoadingBox(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
fun ErrorSnackbar(
    error: String?,
    onDismiss: () -> Unit,
    snackbarHostState: SnackbarHostState,
) {
    LaunchedEffect(error) {
        if (error != null) {
            snackbarHostState.showSnackbar(error)
            onDismiss()
        }
    }
}

@Composable
fun SnackbarContainer(snackbarHostState: SnackbarHostState) {
    SnackbarHost(hostState = snackbarHostState)
}

@Composable
fun ToolTimeline(steps: List<ToolStep>, modifier: Modifier = Modifier) {
    Column(modifier = modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        steps.forEach { step ->
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            ) {
                Column(Modifier.padding(8.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(step.tool, style = MaterialTheme.typography.labelLarge)
                        Text(step.state, style = MaterialTheme.typography.labelSmall)
                    }
                    if (step.args.isNotBlank()) {
                        Text(
                            step.args,
                            style = MaterialTheme.typography.bodySmall,
                            fontFamily = FontFamily.Monospace,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    }
                    step.resultPreview?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
                    }
                    step.durationMs?.let {
                        Text("${it}ms", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
    }
}

@Composable
fun SourceBadge(source: String?) {
    if (source.isNullOrBlank()) return
    val label = when (source) {
        "web" -> "Web"
        "lark" -> "飞书"
        "repl" -> "REPL"
        "heartbeat" -> "心跳"
        else -> source
    }
    Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
}
