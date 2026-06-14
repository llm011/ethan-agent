# REPL 记忆压缩异步化

## 背景与目标

REPL 里的记忆压缩（`consolidator.compress()`）当前是同步阻塞的：
在对话完成后、下一条输入之前，用户必须等待廉价模型 API 调用完成才能继续输入。

**目标：记忆压缩和冷区提取 fire-and-forget，不延迟 REPL 输入就绪时间。**

**性能影响：正收益。** 消除每隔 5 轮对话的输入延迟。

---

## 当前代码状态

`ethan/interface/repl.py` 约第 496 行：

```python
memory.add_turn(msg, resp)

if memory.needs_compression():
    batch = memory.get_compress_batch()
    try:
        summary = await consolidator.compress(batch, memory.warm_summary)  # ← 阻塞
        memory.apply_summary(summary)
    except Exception:
        pass

if memory.needs_cold_extraction():
    try:
        facts_list, condensed = await consolidator.extract_cold(...)        # ← 阻塞
        ...
    except Exception:
        pass
```

---

## 实现方案

### 唯一改动：`ethan/interface/repl.py`

**新增辅助函数**（在文件顶部附近，与其他辅助函数放在一起）：

```python
async def _background_consolidate(
    memory: WorkingMemory,
    consolidator: Consolidator,
    fact_store: FactStore,
    session_id: str,
) -> None:
    """后台执行记忆压缩，不阻塞对话输入。"""
    try:
        if memory.needs_compression():
            batch = memory.get_compress_batch()
            summary = await consolidator.compress(batch, memory.warm_summary)
            memory.apply_summary(summary)

        if memory.needs_cold_extraction():
            facts_list, condensed = await consolidator.extract_cold(
                memory.warm_summary, memory.cold_facts
            )
            for fact in facts_list:
                fact_store.add(fact, confidence=0.8, source=session_id)
            memory.apply_cold_extraction(fact_store.build_context(), condensed)
    except Exception:
        pass  # 后台失败静默处理
```

**替换原来的同步调用**（约第 496 行），把原来的两个 `if` 块替换为：

```python
memory.add_turn(msg, resp)

# 原来是同步阻塞，改为 fire-and-forget
if memory.needs_compression() or memory.needs_cold_extraction():
    asyncio.create_task(
        _background_consolidate(memory, consolidator, fact_store, session.id)
    )
```

---

## 文件改动清单

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `ethan/interface/repl.py` | **修改** | 新增 `_background_consolidate()` 约 18 行；替换 2 个 `if` 块为 1 个 `create_task` |

---

## 验证方法

1. 进行 >5 轮对话触发压缩阈值
2. 观察输入提示符是否立刻就绪（之前会有 1-3 秒等待）
3. 对话结束后检查 `~/.ethan/memory/facts.json` 确认记忆正常沉淀

---

## 注意事项

- `memory.get_compress_batch()` 在 `create_task` 前已经调用会清空缓冲区，
  所以即使 task 还没跑，`needs_compression()` 已经返回 False，不会重复触发。
  但本方案是先检查再 create_task，所以需要确保 task 内部再次调用 `get_compress_batch()`。
  因此保留 `_background_consolidate` 内部的 `needs_compression()` 检查不删，让它自己管状态。
- 所有操作在同一 asyncio event loop 里，没有真正的并发写，不需要加锁
- API 的 `_stream_response` 里已有 `asyncio.create_task(_maybe_consolidate(...))` 是正确的，
  本方案只是让 REPL 对齐 API 的做法
