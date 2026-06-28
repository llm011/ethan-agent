package com.ethan.agent.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ethan.agent.ui.navigation.Screen
import com.ethan.agent.ui.navigation.moreMenuItems

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MoreScreen(onNavigate: (String) -> Unit) {
    Scaffold(topBar = { TopAppBar(title = { Text("更多") }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding)) {
            items(moreMenuItems) { screen ->
                Card(
                    Modifier
                        .padding(horizontal = 12.dp, vertical = 4.dp)
                        .clickable { onNavigate(screen.route) },
                ) {
                    ListItem(
                        headlineContent = { Text(screen.title) },
                        leadingContent = {
                            screen.icon?.let { Icon(it, contentDescription = null) }
                        },
                    )
                }
            }
        }
    }
}
