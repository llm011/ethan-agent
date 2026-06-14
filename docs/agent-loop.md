# Agent Loop 设计文档

当前 Agent Loop 融合了 ReAct 论文、OpenClaw 的分层结构和 nanobot 的极简风格，loop 本身保持精简，复杂性由 Provider / Tool / Memory / Skills 各子系统承担。

---

## 两种模式

| 方法 | 说明 |
|------|------|
| `Agent.chat(messages)` | 非流式，等待完整响应后返回 `Message` |
| `Agent.stream_chat(messages)` | 流式，逐 token yield 文本，tool call 前后推送 `ToolEvent` |

---

## Loop 流程

每次对话开始前，先由 `_is_fast_path()` 决定走快轨还是慢轨：

```
用户输入
   │
   ▼
_is_fast_path() 意图路由
   │
   ├─ Fast Path → 极简 system prompt + 仅 fast_path 工具 + 最多 2 次迭代
   └─ Full Path → 完整 system prompt + 全量工具 + 最多 max_tool_iterations 次迭代
   │
   ▼
for _ in range(max_iters):
    response = await provider.chat(working_messages, tools, system)
    if not response.is_tool_call → return response
    results = await executor.execute(response.tool_calls)  # asyncio.gather 并发
    working_messages.extend(tool_results)

return "[max tool iterations reached]"
```

---

## 系统提示词构建（`_build_system`）

Full Path 按以下顺序拼接，`Current time:` 是稳定层与动态层的分界点（用于 Prompt Caching）：

```
<identity>           ← system/identity.md（稳定，可缓存）
<operating_principles> ← system/soul.md（稳定）
<tools_reference>    ← system/tools.md（稳定）
<available_skills>   ← 所有 Skill 名称列表（稳定）
─── Current time: ───  ← 缓存分割线
workspace 路径
定时任务摘要
<user_context>       ← FactStore top-15 facts
<procedures>         ← ProcedureStore
<relevant_skills>    ← 关键词匹配的 Skill 正文
```

Fast Path 只保留：`identity + Current time: + top-5 facts + 匹配到的 Skill`。

---

## 消息格式

整个 loop 维护 `working_messages` 列表，格式同时兼容 Anthropic 和 OpenAI 协议（各 Provider 负责自己的转换）：

```
[user]       "帮我查一下当前时间"
[assistant]  tool_calls: [shell(command="date")]
[tool]       "Wed Jun 11 13:49:00 CST 2026"
[assistant]  "当前时间是 2026年6月11日 下午1点49分"  ← 最终返回
```

---

## 设计决策

并发执行 tool calls：LLM 有时在一次回复中请求多个 tool，`asyncio.gather()` 并发执行可以显著减少延迟。

max_iterations 上限：防止 LLM 陷入 tool call 死循环（工具持续报错时）。Fast Path 固定为 2，Full Path 默认 10，可通过 config 调整。

UsageStats：`cache_tokens` 同时统计 `cache_read` 和 `cache_creation`，确保状态栏显示的缓存命中数准确。
