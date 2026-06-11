# Agent Loop 设计文档

## 参考来源

当前 Agent Loop 主要参考以下三个项目，取各家精华融合：

### 1. ReAct 论文（核心思想）
> Yao et al., 2022 — *ReAct: Synergizing Reasoning and Acting in Language Models*（ICLR 2023）

**核心思路**：让 LLM 在同一个 context 中交替进行"思考（Thought）"和"行动（Action）"，每次行动后观察结果，再继续思考。这比纯推理或纯行动都更可靠。

```
Thought → Action（tool call）→ Observation（tool result）→ Thought → ...
```

### 2. OpenClaw（7阶段 loop 结构）
OpenClaw 把 loop 拆成了 7 个明确的阶段：消息接收 → Skill 注入 → 记忆加载 → LLM 调用 → Tool 执行 → 记忆写回 → 响应输出。

我们借鉴了它的**结构化分层**思路，每个阶段职责清晰，但当前实现先做精简版，后续阶段逐步补充记忆和 Skill 注入。

### 3. nanobot（极简 loop）
nanobot 的核心 loop 约 200 行，所有复杂性下沉到子模块，loop 本身只做"调用 LLM → 判断是否 tool call → 执行 → 追加结果 → 重复"这几件事。

我们的实现风格更接近 nanobot：**loop 本身保持极简，复杂性由 Provider / Tool / Memory 各子系统承担**。

### 4. Hermes（将在阶段二引入）
Hermes 在 loop 中每 10 轮触发一次"记忆整合"（memory consolidation），让 LLM 自评哪些内容值得持久化，并可能生成新 Skill。这部分在阶段二、三实现。

---

## 当前实现

文件：`ethan/core/agent.py`

### 两种模式

| 方法 | 说明 |
|------|------|
| `Agent.chat(messages)` | 非流式，等待完整响应后返回 `Message` |
| `Agent.stream_chat(messages)` | 流式，逐 token yield 文本，tool call 在后台处理 |

### Loop 伪代码

```python
working_messages = messages.copy()
tools = [所有注册的 tool 定义]

for _ in range(max_iterations):           # 最多 10 次 tool 调用
    response = await provider.chat(working_messages, tools, system)
    working_messages.append(response)

    if not response.is_tool_call:
        return response                   # 正常结束，返回给用户

    # 并发执行所有 tool calls
    results = await executor.execute(response.tool_calls)
    for result in results:
        working_messages.append(tool_result_message)
    # 继续下一轮

return "[达到最大工具调用次数]"           # 安全退出
```

### 设计决策说明

**为什么并发执行 tool calls？**
LLM 有时会在一次回复中请求多个 tool（如同时查文件和执行命令）。并发执行可以显著减少延迟，`asyncio.gather()` 天然支持。

**为什么有 max_iterations 上限？**
防止 LLM 陷入 tool call 死循环（如工具一直报错，LLM 一直重试）。默认 10 次，可通过 `config.yaml` 调整。

**messages 列表的格式**
整个 loop 维护一个 `working_messages` 列表，结构如下：

```
[user]       "帮我查一下当前时间"
[assistant]  tool_calls: [shell(command="date")]
[tool]       "Wed Jun 11 13:49:00 CST 2026"
[assistant]  "当前时间是 2026年6月11日 下午1点49分"  ← 最终返回这条
```

这个格式同时兼容 Anthropic 和 OpenAI 协议（两个 Provider 各自负责转换为自己的格式）。

---

## 未来扩展（阶段二后）

```
for _ in range(max_iterations):
    response = await provider.chat(
        working_messages + [skill_context],   # ← 阶段三：注入相关 Skill
        tools,
        system + persistent_memory_summary,  # ← 阶段二：注入持久记忆摘要
    )
    ...

# loop 结束后
if turn_count % 10 == 0:
    await memory_consolidator.run(working_messages)  # ← 阶段二：记忆压缩
```

---

## 消息类型参考

```python
# 普通用户消息
Message(role="user", content="你好")

# LLM 普通回复
Message(role="assistant", content="你好！有什么可以帮你？")

# LLM 请求 tool call
Message(
    role="assistant",
    content="",                         # 可为空
    tool_calls=[
        ToolCall(id="call_abc", name="shell", arguments={"command": "date"})
    ]
)

# tool 执行结果（回传给 LLM）
Message(role="tool", content="Wed Jun 11 ...", tool_call_id="call_abc")
```
