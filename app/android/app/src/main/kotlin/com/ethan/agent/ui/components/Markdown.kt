package com.ethan.agent.ui.components

import android.content.Intent
import android.net.Uri
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import dev.jeziellago.compose.markdowntext.MarkdownText

@Composable
fun SimpleMarkdown(text: String, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    MarkdownText(
        markdown = text,
        modifier = modifier,
        style = MaterialTheme.typography.bodyMedium.copy(
            color = MaterialTheme.colorScheme.onSurface,
        ),
        onLinkClicked = { url ->
            runCatching {
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            }
        },
    )
}
