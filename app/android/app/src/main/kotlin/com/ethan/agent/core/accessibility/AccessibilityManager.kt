package com.ethan.agent.core.accessibility

import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription

/**
 * 无障碍管理器 - 提升应用可访问性
 */
object AccessibilityManager {
    
    /**
     * 为 Composable 添加无障碍标签
     */
    fun Modifier.accessibleLabel(label: String): Modifier = this.semantics {
        contentDescription = label
    }
    
    /**
     * 为按钮添加语义角色
     */
    fun Modifier.buttonRole(): Modifier = this.semantics {
        role = Role.Button
    }
}

/**
 * 扩展函数：添加无障碍点击处理
 */
fun Modifier.accessibleClickable(
    onClick: () -> Unit,
    contentDescription: String,
): Modifier = this
    .clickable(
        indication = null,
        interactionSource = remember { MutableInteractionSource() },
        onClick = onClick,
    )
    .semantics {
        this.contentDescription = contentDescription
        this.role = Role.Button
    }
