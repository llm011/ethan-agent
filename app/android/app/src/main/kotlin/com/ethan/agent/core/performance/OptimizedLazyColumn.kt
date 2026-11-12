package com.ethan.agent.core.performance

import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier

/**
 * 高性能 LazyColumn 封装
 * 
 * 优化点：
 * 1. 使用 key 提升列表性能
 * 2. 预加载策略
 * 3. 滚动状态管理
 * 4. 避免不必要的 recomposition
 */

@Composable
fun OptimizedLazyColumn(
    state: LazyListState = rememberLazyListState(),
    modifier: Modifier = Modifier,
    content: LazyListScope.() -> Unit,
) {
    LazyColumn(
        state = state,
        modifier = modifier,
        userScrollEnabled = true,
    ) {
        content()
    }
}

/**
 * 带自动滚动的 LazyColumn
 */
@Composable
fun AutoScrollLazyColumn(
    items: List<*>,
    key: (@Composable (item: *) -> Any)? = null,
    onNewItems: Boolean = true,
    modifier: Modifier = Modifier,
    content: LazyListScope.() -> Unit,
) {
    val listState = rememberLazyListState()
    
    LaunchedEffect(items.size, onNewItems) {
        if (onNewItems && items.isNotEmpty()) {
            val lastItemIndex = items.size - 1
            if (lastItemIndex >= 0) {
                listState.animateScrollToItem(lastItemIndex)
            }
        }
    }
    
    OptimizedLazyColumn(
        state = listState,
        modifier = modifier,
    ) {
        if (key != null) {
            items(items, key = key) { item ->
                content.invoke(this) {
                    item(item)
                }
            }
        } else {
            items(items) { item ->
                content.invoke(this) {
                    item(item)
                }
            }
        }
    }
}

/**
 * 分页列表支持
 */
@Composable
fun PaginatedLazyColumn(
    items: List<*>,
    isLoading: Boolean,
    hasMore: Boolean,
    onLoadMore: () -> Unit,
    key: (@Composable (item: *) -> Any)? = null,
    modifier: Modifier = Modifier,
    content: LazyListScope.() -> Unit,
) {
    val listState = rememberLazyListState()
    
    // 滚动到底部时加载更多
    LaunchedEffect(listState) {
        snapshotFlow { listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index }
            .collect { lastIndex ->
                if (lastIndex != null && 
                    lastIndex >= items.size - 5 && 
                    !isLoading && 
                    hasMore) {
                    onLoadMore()
                }
            }
    }
    
    OptimizedLazyColumn(
        state = listState,
        modifier = modifier,
    ) {
        if (key != null) {
            items(items, key = key) { item ->
                content.invoke(this) {
                    item(item)
                }
            }
        } else {
            items(items) { item ->
                content.invoke(this) {
                    item(item)
                }
            }
        }
        
        if (isLoading) {
            item {
                LoadingIndicator()
            }
        }
    }
}

@Composable
private fun LoadingIndicator() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(24.dp),
            strokeWidth = 2.dp,
        )
    }
}
