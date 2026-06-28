package com.ethan.agent.ui.memory

import com.ethan.agent.core.model.Fact

/** Facts from API have no id; backend uses array index for PATCH/DELETE. */
data class FactItem(
    val index: String,
    val fact: Fact,
)

fun List<Fact>.toFactItems(includeSuperseded: Boolean = false): List<FactItem> {
    return mapIndexedNotNull { index, fact ->
        if (!includeSuperseded && fact.superseded) return@mapIndexedNotNull null
        FactItem(index = index.toString(), fact = fact)
    }
}

fun List<Fact>.indexOfFact(target: Fact): String {
    val idx = indexOfFirst { it.content == target.content && it.createdAt == target.createdAt }
    return if (idx >= 0) idx.toString() else "0"
}
