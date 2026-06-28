package com.ethan.agent.ui.components

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle

@Composable
fun SimpleMarkdown(text: String, modifier: androidx.compose.ui.Modifier = androidx.compose.ui.Modifier) {
    Text(
        text = parseSimpleMarkdown(text),
        style = MaterialTheme.typography.bodyMedium,
        modifier = modifier,
    )
}

private fun parseSimpleMarkdown(source: String): AnnotatedString = buildAnnotatedString {
    source.lines().forEachIndexed { index, line ->
        if (index > 0) append("\n")
        when {
            line.startsWith("### ") -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                append(line.removePrefix("### "))
            }
            line.startsWith("## ") -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                append(line.removePrefix("## "))
            }
            line.startsWith("# ") -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
                append(line.removePrefix("# "))
            }
            line.startsWith("```") -> withStyle(SpanStyle(fontFamily = FontFamily.Monospace)) {
                append(line)
            }
            line.startsWith("- ") || line.startsWith("* ") -> append("• ${line.drop(2)}")
            else -> append(line)
        }
    }
}
