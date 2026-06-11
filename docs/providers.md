# Provider 层设计文档

## 职责

Provider 层是 Ethan 与 LLM API 之间的适配层，负责：
1. 屏蔽不同厂商的协议差异（Anthropic vs OpenAI）
2. 统一消息格式转换（内部 `Message` ↔ 各厂商格式）
3. 支持同步调用和流式输出两种模式
4. 根据 model 名称自动路由到正确的 Provider

---

## 接口设计（`ethan/providers/base.py`）

### 核心数据结构

```python
# 工具定义（传给 LLM 用）
ToolDefinition(name, description, parameters)   # parameters 是 JSON Schema

# 一次 tool call 请求
ToolCall(id, name, arguments)                   # arguments 是 dict

# 统一消息格式
Message(role, content, tool_calls=[], tool_call_id=None)

# 流式输出的一个 chunk
StreamChunk(content, tool_calls=[], is_final=False)
```

### BaseProvider 抽象接口

```python
class BaseProvider(ABC):
    async def chat(messages, tools=None, system=None) -> Message
    async def stream_chat(messages, tools=None, system=None) -> AsyncIterator[StreamChunk]
    model: str  # 当前使用的模型名
```

所有 Provider 必须实现这两个方法。上层（Agent Loop）只依赖这个接口，不关心底层是 Claude 还是 GPT。

---

## Anthropic Provider（`ethan/providers/anthropic.py`）

### 协议特点

Anthropic 的 tool_use 格式与 OpenAI 不同，主要区别：

| 项目 | Anthropic | OpenAI |
|------|-----------|--------|
| tool result 消息的 role | `user`（包在 content 数组里） | `tool` |
| tool call 的字段名 | `tool_use`，input 是 dict | `function`，arguments 是 JSON 字符串 |
| 流式 tool call | `input_json_delta` 事件 | `delta.tool_calls` |

### 消息转换逻辑

内部 `Message` → Anthropic 格式：
- `role="tool"` → `{"role": "user", "content": [{"type": "tool_result", ...}]}`
- `role="assistant"` 且有 tool_calls → content 数组包含 text block + tool_use block

### 流式处理

Anthropic 流式事件序列：
```
content_block_start(type=tool_use)  → 记录 tool id/name
input_json_delta                    → 累积 JSON 字符串
message_stop                        → 解析完整 JSON，yield 最终 StreamChunk
```

---

## OpenAI 兼容 Provider（`ethan/providers/openai_compat.py`）

### 支持的模型/服务

通过配置 `base_url` 可以接入：

| 服务 | base_url |
|------|----------|
| OpenAI 官方 | 不填（默认） |
| Ollama（本地） | `http://localhost:11434/v1` |
| LM Studio | `http://localhost:1234/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| 任何 OpenAI 兼容 API | 自定义 |

### 协议特点

- tool call 的 arguments 是 JSON **字符串**（不是 dict），需要 `json.loads()`
- 流式结束条件：`finish_reason == "tool_calls"` 或 `"stop"`
- tool result 消息的 role 就是 `"tool"`（不需要包在 user 消息里）

---

## Provider Manager（`ethan/providers/manager.py`）

### 路由规则

`create_provider(model)` 根据 model 名前缀自动选择 Provider：

```
claude-*          → AnthropicProvider
gpt-*, o1-*, o3-* → OpenAICompatProvider
其他              → 根据 config.agent.default_provider
未指定 model      → 根据 config.agent.default_provider
```

### 配置方式

`.env` 文件：
```env
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_DEFAULT_MODEL=claude-sonnet-4-6

OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=http://localhost:11434/v1   # Ollama，可选
OPENAI_DEFAULT_MODEL=gpt-4o

AGENT_DEFAULT_PROVIDER=anthropic
AGENT_MAX_TOKENS=4096
AGENT_MAX_TOOL_ITERATIONS=10
```

---

## 扩展：新增 Provider

只需继承 `BaseProvider` 并实现两个方法：

```python
# ethan/providers/gemini.py
class GeminiProvider(BaseProvider):
    async def chat(self, messages, tools=None, system=None) -> Message:
        ...
    async def stream_chat(self, messages, tools=None, system=None):
        ...
```

然后在 `manager.py` 的路由规则里加一个 `gemini-*` 分支即可。
