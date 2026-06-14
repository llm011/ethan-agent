# Skill 条件路由（channel 过滤）

## 背景与目标

当前所有 Skill 对所有渠道（Web、飞书、REPL）一视同仁，trigger 命中就注入。
问题：全屋智能 Skill 在 Web 工作对话里也会被触发；某些只适用飞书的 Skill 在 Web 端也生效。

**目标：Skill frontmatter 支持 `channels` 字段，Agent 路由时按渠道过滤。**

**性能影响：极小。** 只在 `match()` 里增加一个列表包含检查，< 0.1ms。

---

## 当前代码状态

`ethan/skills/loader.py`，`Skill` dataclass 当前字段：
```python
name, description, trigger, content, source, builtin, fast_path
```
无 `channels` 字段。

`ethan/skills/registry.py`，`match()` 只做 trigger 子串匹配，无渠道过滤。

`ethan/core/agent.py`，`chat()` 创建 Agent 时不传渠道信息。

---

## 实现方案

### 1. 扩展 `Skill` dataclass（`ethan/skills/loader.py`）

```python
from dataclasses import dataclass, field

@dataclass
class Skill:
    name: str
    description: str
    trigger: list[str]
    content: str
    source: Path
    builtin: bool = False
    fast_path: bool = False
    channels: list[str] = field(default_factory=list)  # 新增：[] 表示所有渠道
```

在 `load_skill_from_file()` 中解析（在 `fast_path` 解析后加）：

```python
channels_raw = meta.get("channels", [])
if isinstance(channels_raw, str):
    channels = [c.strip() for c in channels_raw.split(",") if c.strip()]
elif isinstance(channels_raw, list):
    channels = channels_raw
else:
    channels = []

return Skill(..., channels=channels)
```

### 2. 扩展 `SkillRegistry.match()` 和 `build_context()`（`ethan/skills/registry.py`）

```python
def match(self, query: str, channel: str = "") -> list[Skill]:
    """按触发词匹配，同时过滤 channel。

    channel: 当前渠道，如 "web"、"lark"、"repl"。
    Skill.channels 为空列表表示适用所有渠道。
    """
    query_lower = query.lower()
    matched = []
    for skill in self._skills:
        # channel 过滤：skill 有限制且当前渠道不在列表中 → 跳过
        if skill.channels and channel and channel not in skill.channels:
            continue
        for trigger in skill.trigger:
            if _match_keyword(trigger, query_lower):   # 已有的通配符匹配函数
                matched.append(skill)
                break
    return matched

def build_context(self, query: str, max_skills: int = 3, channel: str = "") -> str:
    matched = self.match(query, channel=channel)[:max_skills]
    ...  # 其余不变
```

### 3. `Agent` 支持 channel 参数（`ethan/core/agent.py`）

```python
def __init__(self, ..., channel: str = ""):
    ...
    self._channel = channel    # 新增
```

在 `_build_system()` 里 Skill 匹配时带上：

```python
# 两处 build_context 调用都改为：
skill_ctx = self._skills.build_context(last_user, channel=self._channel)
```

同样，`fast_path` 的 skill_triggers 收集处：

```python
skill_triggers = [
    kw for s in (self._skills.all() if self._skills else [])
    if s.fast_path and (not s.channels or self._channel in s.channels or not self._channel)
    for kw in s.trigger
]
```

### 4. 各入口传入 channel

**`ethan/interface/api.py`** 的 `ChatRequest` 和 `_create_agent()`：

```python
class ChatRequest(BaseModel):
    ...
    channel: str = "web"    # 新增，默认 web，向后兼容

def _create_agent(model=None, channel: str = "web") -> Agent:
    ...
    return Agent(tool_registry=registry, skill_registry=skills, model=model, channel=channel)

@app.post("/chat", ...)
async def chat(req: ChatRequest):
    agent = _create_agent(req.model, channel=req.channel)
```

**`ethan/interface/lark_events.py`**：

```python
agent = Agent(tool_registry=registry, skill_registry=skills, channel="lark")
```

**`ethan/interface/repl.py`**（创建 agent 处）：

```python
agent = Agent(tool_registry=registry, skill_registry=skills, channel="repl")
```

---

## Skill frontmatter 示例

```yaml
# 全屋智能：只在 repl 和 lark 渠道生效
---
name: home-assistant
channels:
  - repl
  - lark
---

# 通用 Skill：所有渠道（channels 留空或不写）
---
name: time-management
channels: []
---
```

---

## 文件改动清单

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `ethan/skills/loader.py` | **修改** | dataclass +1 字段，解析 +5 行 |
| `ethan/skills/registry.py` | **修改** | `match()` 和 `build_context()` 各加 `channel` 参数，约 6 行 |
| `ethan/core/agent.py` | **修改** | `__init__` +1 字段，`_build_system` 传参 2 处，约 5 行 |
| `ethan/interface/api.py` | **修改** | `ChatRequest` +1 字段，`_create_agent` 传参，约 5 行 |
| `ethan/interface/lark_events.py` | **修改** | Agent 初始化 +1 参数，1 行 |
| `ethan/interface/repl.py` | **修改** | Agent 初始化 +1 参数，1 行 |

---

## 验证方法

```bash
# 1. 创建一个 channels: [repl] 的测试 Skill
cat > ~/.ethan/skills/test-repl-only.md << 'EOF'
---
name: test-repl-only
description: 仅 REPL 道测试 Skill
trigger: 测试渠道过滤
channels:
  - repl
---
这是一个只在 REPL 里生效的测试 Skill。
EOF

# 2. Web UI 发送"测试渠道过滤"，检查 /system-prompt-preview
# 该 Skill 不应出现在 prompt 里

# 3. REPL 发送同样消息
# 该 Skill 应出现在 prompt 里
ethan -p "测试渠道过滤"
```

---

## 注意事项

- 已有 Skill 不写 `channels` 等价于 `channels: []`（所有渠道），行为不变，完全向后兼容
- Web UI 前端发 chat 请求不传 `channel` 时，后端默认 `"web"`，不需要前端改动
- `channels` 和 `fast_skill_triggers` 是独立的——channel 过滤决定 Skill 是否注入，fast_path 决定走哪条路由
