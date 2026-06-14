# 主动记忆写入与 Skill 自生成

## 背景与目标

当前 Ethan 只能被动地沉淀记忆：
- `consolidator` 在后台攒够若干轮才压缩提取，有延迟
- `ProcedureStore` 只检测纠正信号（"不对"、"应该"等）

**问题**：用户说"你以后可以用这个短语激励我"，Agent 当时只是回复了，没有主动把这个偏好写入记忆。

**目标**：让 Agent 像人一样，在对话中识别到值得记住的信息时，**立刻**主动写入——偏好、个人信息、行为指令、值得复用的模式（Skill）——不等批量处理，当场保存。

---

## 根本原因分析

Agent 做不到主动写记忆，是因为：
1. 没有可以直接写入 FactStore / ProcedureStore 的**工具**
2. System prompt 里没有**主动写记忆**的指令

只要补上这两点，大模型自己完全能判断"这句话值得记住"——它的语义理解能力远超任何规则匹配。

---

## 实现方案

### 一、新建写记忆工具

#### 1. `ethan/tools/builtin/memory_write.py`（新建）

```python
"""主动写记忆工具——Agent 在对话中主动保存值得记住的信息。"""

from ethan.tools.base import BaseTool


class MemoryWriteTool(BaseTool):
    name = "memory_write"
    description = (
        "将值得长期记住的信息写入持久记忆。"
        "用于保存用户偏好、个人信息、行为指令、重要决定等。"
        "当用户表达偏好（'我喜欢/不喜欢'）、给出行为指令（'你以后要/可以'）、"
        "分享个人信息（'我的X是Y'）时，主动调用此工具。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "要记住的内容，一句话描述，清晰具体。例如：'用户希望被短语 Roots run deep 激励坚持'"
            },
            "category": {
                "type": "string",
                "enum": ["preference", "decision", "knowledge", "instruction"],
                "description": "preference=用户偏好，decision=重要决定，knowledge=用户分享的信息，instruction=用户给出的行为指令"
            },
        },
        "required": ["content", "category"],
    }
    fast_path: bool = False  # 只在 Full Path 使用，Fast Path 无需写记忆

    async def run(self, content: str, category: str = "knowledge") -> str:
        from ethan.memory.facts import FactStore
        store = FactStore()
        store.add(content, confidence=0.95, source="agent_proactive", category=category)
        return f"已记住：{content}"
```

#### 2. `ethan/tools/builtin/procedure_write.py`（新建）

```python
"""主动写行为准则工具——保存用户给出的对 Agent 行为的指令。"""

from ethan.tools.base import BaseTool


class ProcedureWriteTool(BaseTool):
    name = "procedure_write"
    description = (
        "将用户给出的行为指令写入行为准则，影响 Agent 未来所有对话的行为。"
        "用于保存'以后你要这样做'、'你可以用X方式'等持久行为指令。"
        "与 memory_write 的区别：这里保存的是对 Agent 行为的指令，而非用户信息。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "rule": {
                "type": "string",
                "description": "行为规则，描述 Agent 应该怎么做。例如：'在适当时机用 Roots run deep 激励用户坚持'"
            },
            "context": {
                "type": "string",
                "description": "触发这条规则的场景描述（可选）"
            },
        },
        "required": ["rule"],
    }
    fast_path: bool = False

    async def run(self, rule: str, context: str = "") -> str:
        from ethan.memory.procedures import ProcedureStore
        store = ProcedureStore()
        store.add(rule, context=context)
        return f"已记住行为准则：{rule}"
```

#### 3. `ethan/tools/builtin/skill_create.py`（新建）

```python
"""主动创建 Skill 工具——当对话中出现值得复用的模式时自动创建技能。"""

from ethan.tools.base import BaseTool


class SkillCreateTool(BaseTool):
    name = "skill_create"
    description = (
        "创建一个新的 Skill 文件，保存可复用的操作模式或流程。"
        "当用户教会 Agent 一种新的处理方式，且这个方式未来可能反复用到时，调用此工具。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill 名称，英文 kebab-case，如 motivate-user"
            },
            "description": {
                "type": "string",
                "description": "这个 Skill 的一句话描述"
            },
            "trigger": {
                "type": "string",
                "description": "触发关键词，用 | 分隔，如 '激励|坚持|鼓励'"
            },
            "content": {
                "type": "string",
                "description": "Skill 的详细说明，描述如何执行这个技能"
            },
        },
        "required": ["name", "description", "trigger", "content"],
    }
    fast_path: bool = False

    async def run(self, name: str, description: str, trigger: str, content: str) -> str:
        import re
        import yaml
        from ethan.skills.loader import USER_SKILLS_DIR

        # 安全处理名称
        safe_name = re.sub(r"[^a-z0-9\-]", "-", name.lower()).strip("-")
        if not safe_name:
            return "Skill 名称无效"

        skill_dir = USER_SKILLS_DIR / safe_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"

        # 如果已存在，不覆盖
        if skill_file.exists():
            return f"Skill '{safe_name}' 已存在，未覆盖"

        triggers = [t.strip() for t in trigger.split("|") if t.strip()]
        frontmatter = {
            "name": safe_name,
            "description": description,
            "trigger": triggers,
        }
        text = f"---\n{yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)}---\n\n{content}"
        skill_file.write_text(text, encoding="utf-8")

        return f"已创建 Skill：{safe_name}（触发词：{trigger}）"
```

---

### 二、注册工具到 Agent

修改 `ethan/interface/api.py` 的 `_create_agent()` 和 `ethan/interface/lark_events.py` 的 `_handle_message()`，加入三个新工具：

```python
from ethan.tools.builtin.memory_write import MemoryWriteTool
from ethan.tools.builtin.procedure_write import ProcedureWriteTool
from ethan.tools.builtin.skill_create import SkillCreateTool

# 在工具注册时加入：
registry.register(MemoryWriteTool())
registry.register(ProcedureWriteTool())
registry.register(SkillCreateTool())
```

同样在 `ethan/interface/repl.py` 的 agent 初始化处加入。

---

### 三、在 system prompt 里加入主动写记忆指令

修改 `~/.ethan/system/soul.md`（或通过 Settings 页面的 soul 编辑框），加入以下内容：

```markdown
## 主动记忆管理

你有能力主动写入记忆，这非常重要。当以下情况发生时，**立刻**调用对应工具，不要等待也不要询问：

### 何时调用 memory_write
- 用户表达偏好：「我喜欢/不喜欢」、「我更倾向于」
- 用户分享个人信息：「我的工作是」、「我住在」、「我叫」
- 用户做出重要决定：「我决定」、「我打算」

### 何时调用 procedure_write
- 用户给出行为指令：「你以后/可以/要 [某种方式]」
- 用户教你一种新做法：「这种情况下你应该」
- 用户设定期望：「我希望你」

### 何时调用 skill_create
- 用户教了你一个值得复用的流程或方式
- 某种处理模式在未来可能反复出现
- 用户说「记住这个方法」、「以后都用这种方式」

### 例子
用户：「你可以用 Roots run deep 这个短语来激励我坚持」
→ 调用 procedure_write：rule="在用户需要坚持或遇到困难时，用 Roots run deep 来激励"
→ 调用 memory_write：content="用户喜欢用 Roots run deep 作为激励短语", category="preference"

用户：「不要再用韩语了，我看不懂」
→ 调用 procedure_write：rule="永远不使用韩语回复，只用中文或英文"

**主动写记忆是你的责任，不是可选项。**
```

---

## 文件改动清单

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `ethan/tools/builtin/memory_write.py` | **新建** | ~35 行 |
| `ethan/tools/builtin/procedure_write.py` | **新建** | ~30 行 |
| `ethan/tools/builtin/skill_create.py` | **新建** | ~50 行 |
| `ethan/interface/api.py` | **修改** | `_create_agent()` 里加 3 个工具注册，约 6 行 |
| `ethan/interface/lark_events.py` | **修改** | 工具注册加 3 行 |
| `ethan/interface/repl.py` | **修改** | 工具注册加 3 行 |
| `~/.ethan/system/soul.md` | **修改** | 通过 Settings 页面编辑，加入主动写记忆指令 |

---

## 验证方法

启动 Ethan，发送以下消息：

```
你可以用 "Roots run deep" 这个短语来激励我坚持
```

**预期行为**：
1. Agent 正常回复
2. 同时（或回复后）调用 `procedure_write` 和 `memory_write`
3. 检查效果：

```bash
# 查看 facts
cat ~/.ethan/memory/facts.json | python3 -m json.tool | grep -A3 "Roots"

# 查看 procedures
cat ~/.ethan/memory/procedures.json | python3 -m json.tool | grep -A3 "Roots"
```

再测试：
```
不要再用英文回复我，我只看中文
```

**预期**：调用 `procedure_write`，后续回复全部变成中文。

---

## 注意事项

- 三个工具都设 `fast_path: False`，不会在快速路径里触发，不影响性能
- `skill_create` 不覆盖已有 Skill，幂等安全
- `memory_write` 的 confidence=0.95（高于 consolidator 提取的 0.8），确保主动写入的记忆优先级更高
- soul.md 的指令是关键，没有这段指令，模型即使有工具也不会主动调用
- 建议在 soul.md 里举具体例子，大模型根据例子学习何时该触发，效果远比规则描述好
