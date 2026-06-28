package com.ethan.agent.ui.docs

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import com.ethan.agent.ui.components.SimpleMarkdown

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DocsScreen(
    state: DocsUiState,
    onSelectDoc: (String) -> Unit,
    onClearError: () -> Unit,
    showListOnly: Boolean = false,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    Scaffold(
        topBar = { TopAppBar(title = { Text("文档") }) },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        if (state.isLoading) {
            LoadingBox(Modifier.padding(padding))
            return@Scaffold
        }

        if (showListOnly || state.selectedSlug == null) {
            LazyColumn(Modifier.fillMaxSize().padding(padding).padding(12.dp)) {
                items(state.docs, key = { it.slug }) { doc ->
                    Card(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 4.dp)
                            .clickable { onSelectDoc(doc.slug) },
                    ) {
                        Text(doc.title, modifier = Modifier.padding(16.dp), style = MaterialTheme.typography.titleSmall)
                    }
                }
            }
        } else {
            Column(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
            ) {
                SimpleMarkdown(text = state.content)
            }
        }
    }
}
