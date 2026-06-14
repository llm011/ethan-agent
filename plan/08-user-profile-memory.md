# 用户画像层（UserProfile）与记忆类型扩展

## 背景与问题

Ethan 当前记忆系统缺少一个核心层次：**用户画像**。

参考 Hermes Agent 的设计，它维护了两个长期记忆文档：
- `MEMORY.md` — Agent 自己的通用记忆
- `USER.md` — 专门的用户画像：用户是谁、目标、工作方式、关系约定

**Ethan 当前的问题：**
当用户说"你可以用 Roots run deep 这个短语来激励我坚持"，这不是一个"事实"，
也不是一条"行为规则"。它是一种**关系语境**——用户与 Agent 之间的私人约定、
个人语言。当前的 FactStore/ProcedureStore 都不是这类内容的合适归宿。

## 记忆类型完整分类

| 类型 | 当前实现 | 特征 | 例子 |
|------|---------|------|------|
| 事实（Facts） | ✅ FactStore | 结构化条目，带置信度 | "用户是软件工程师" |
| 行为规则（Procedures） | ✅ ProcedureStore | Agent 应该怎么做 | "不要用韩语回复" |
| 会话摘要（Episodes） | ✅ EpisodeStore | 历史对话记录 | "上周讨论了全屋智能方案" |
| 工作记忆（Working） | ✅ WorkingMemory | 当前对话上下文 | 热/温/冷窗口 |
| **用户画像（Profile）** | ❌ **缺失** | 叙事型文档，讲述"这个人是谁" | 见下方 |

**用户画像包含的内容：**
- **身份与背景**：职业、角色、所处阶段
- **目标与方向**：短期目标、长期方向、正在做什么
- **工作方式**：偏好的沟通风格、节奏、深度
- **个人语言**：私人短语、口头禅、inside references
- **激励与情感**：什么能激励他、什么让他有压力、如何在困难时帮他
- **关系约定**：用户与 Agent 之间的特殊约定

---

## 实现方案

### 一、用户画像文件

路径：`~/.ethan/memory/user_profile.md`

初始模板（Agent 在 onboarding 或 `profile_update` 首次调用时创建）：

```markdown
# 用户画像

## 身份与背景
（待填充）

## 目标与方向
（待填充）

## 工作与沟通方式
（待填充）

## 个人语言与激励
（待填充）

## 与 Agent 的约定
（待填充）
```

### 二、新建 `profile_update` 工具（`ethan/tools/builtin/profile_update.py`）

```python
"""用户画像更新工具——更新或追加用户画像的特定章节。"""

from ethan.tools.base import BaseTool

_VALID_SECTIONS = [
    "身份与背景",
    "目标与方向",
    "工作与沟通方式",
    "个人语言与激励",
    "与 Agent 的约定",
]


class ProfileUpdateTool(BaseTool):
    name = "profile_update"
    description = (
        "更新用户画像文档的特定章节。用于记录用户的个人语境、关系约定、激励方式等"
        "不属于孤立事实也不属于行为规则的信息。"
        "例如：私人短语、个人目标叙述、沟通风格偏好、与 Agent 的特殊约定。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": _VALID_SECTIONS,
                "description": "要更新的章节名称",
            },
            "content": {
                "type": "string",
                "description": "该章节的新内容（追加或覆盖）",
            },
            "mode": {
                "type": "string",
                "enum": ["append", "overwrite"],
                "description": "append=追加到现有内容；overwrite=完全替换该章节",
                "default": "append",
            },
        },
        "required": ["section", "content"],
    }
    fast_path: bool = False

    async def run(self, section: str, content: str, mode: str = "append") -> str:
        from pathlib import Path
        from ethan.core.config import CONFIG_DIR

        profile_path = CONFIG_DIR / "memory" / "user_profile.md"
        profile_path.parent.mkdir(parents=True, exist_ok=True)

        if not profile_path.exists():
            # 创建初始模板
            sections = _VALID_SECTIONS
            template = "# 用户画像\n\n" + "\n\n".join(
                f"## {s}\n（待填充）" for s in sections
            )
            profile_path.write_text(template, encoding="utf-8")

        text = profile_path.read_text(encoding="utf-8")
        header = f"## {section}"

        if header not in text:
            # 章节不存在，直接追加
            text = text.rstrip() + f"\n\n{header}\n{content}\n"
        else:
            # 找到章节，替换或追加
            lines = text.split("\n")
            in_section = False
            section_start = -1
            next_section_start = -1

            for i, line in enumerate(lines):
                if line.strip() == header:
                    in_section = True
                    section_start = i
                elif in_section and line.startswith("## ") and i > section_start:
                    next_section_start = i
                    break

            if mode == "overwrite":
                # 替换章节内容
                before = lines[:section_start + 1]
                after = lines[next_section_start:] if next_section_start != -1 else []
                new_lines = before + ["", content, ""] + after
                text = "\n".join(new_lines)
            else:
                # 追加到章节末尾
                insert_pos = next_section_start if next_section_start != -1 else len(lines)
                lines.insert(insert_pos, "")
                lines.insert(insert_pos, f"- {content}")
                text = "\n".join(lines)

        profile_path.write_text(text.strip() + "\n", encoding="utf-8")
        return f"已更新用户画像「{section}」：{content[:50]}{'...' if len(content) > 50 else ''}"
```

### 三、在 `_build_system()` 里注入用户画像

修改 `ethan/core/agent.py` 的 `_build_system()` Full Path 部分，在 facts 之前注入 user_profile.md：

```python
# 在 facts_ctx 注入前加入（约第 197 行附近）：
from pathlib import Path as _Path
_profile_path = _Path(workspace) / "memory" / "user_profile.md"
if _profile_path.exists():
    _profile_content = _profile_path.read_text(encoding="utf-8").strip()
    if _profile_content and "（待填充）" not in _profile_content.replace("\n", ""):
        # 只有有实质内容时才注入（避免空模板浪费 token）
        parts.append(
            f"<user_profile>\n"
            f"[System note: This is a comprehensive profile of the user. "
            f"Use it to personalize all responses.]\n\n"
            f"{_profile_content}\n"
            f"</user_profile>"
        )
```

### 四、注册 profile_update 工具

在 `ethan/interface/api.py`、`ethan/interface/lark_events.py`、`ethan/interface/repl.py` 的工具注册处加入（和 plan/07 的三个工具一起注册）：

```python
from ethan.tools.builtin.profile_update import ProfileUpdateTool
registry.register(ProfileUpdateTool())
```

### 五、更新 soul.md 里的工具使用指南

在 plan/07 的 soul.md 内容基础上，补充 profile_update 的触发条件：

```markdown
### 何时调用 profile_update
- 用户分享个人语言、私人短语、inside references：「我用X来激励自己」
- 用户描述自己的目标或方向：「我现在在做X，目标是Y」
- 用户表达沟通偏好：「我喜欢简洁的回复」、「你可以直接说」
- 用户与你建立特殊约定：「你可以用X方式来Y」
- 用户介绍自己：「我是X，负责Y」

### memory_write vs profile_update 的区别
- memory_write：独立的、可验证的事实条目，如「用户使用 Mac mini」
- profile_update：需要放在上下文里理解的人物叙述，如「用户用 Roots run deep 作为坚持的精神口号」
  → 后者放在 profile 的「个人语言与激励」章节里更自然

### 例子
用户：「你可以用 Roots run deep 这个短语来激励我坚持」
→ profile_update：section="个人语言与激励", content="个人口号 Roots run deep：当遇到困难或想放弃时，用这句话激励坚持"
→ procedure_write：rule="在用户遇到挫折或犹豫时，适时用 Roots run deep 鼓励他坚持到底"
```

---

## 文件改动清单

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `ethan/tools/builtin/profile_update.py` | **新建** | ~70 行 |
| `ethan/core/agent.py` | **修改** | `_build_system()` 注入 user_profile.md，约 10 行 |
| `ethan/interface/api.py` | **修改** | 注册 ProfileUpdateTool，1 行 |
| `ethan/interface/lark_events.py` | **修改** | 注册，1 行 |
| `ethan/interface/repl.py` | **修改** | 注册，1 行 |
| `~/.ethan/system/soul.md` | **修改** | 通过 Settings 页面编辑，补充 profile_update 指南 |

---

## 验证方法

```bash
# 1. 触发画像更新
# 发送：「你可以用 Roots run deep 这个短语来激励我坚持」
# 预期：Agent 调用 profile_update，写入「个人语言与激励」章节

# 2. 查看画像文件
cat ~/.ethan/memory/user_profile.md

# 3. 测试注入效果
# GET /system-prompt-preview，应在 Full Path prompt 中看到 <user_profile> 块

# 4. 验证后续对话能使用
# 发送：「我有点想放弃了」
# 预期：Agent 使用 Roots run deep 来回应
```

---

## 与现有记忆系统的协作关系

```
用户说话
    │
    ├─ 是事实/偏好条目？ → memory_write → FactStore
    │   「我的手机号是...」「我不喜欢太长的回复」
    │
    ├─ 是行为指令/纠正？ → procedure_write → ProcedureStore
    │   「不要用韩语」「这种情况你应该...」
    │
    ├─ 是个人语境/关系约定？ → profile_update → user_profile.md
    │   「用这个短语激励我」「我现在在做X」「你可以这样跟我说话」
    │
    └─ 是可复用的操作模式？ → skill_create → ~/.ethan/skills/
        「记住这个处理方法」「以后都用这种方式」
```

---

## 注意事项

- user_profile.md 是叙事型文档，用 markdown 节（`##`）组织，LLM 友好
- 只有有实质内容时才注入 prompt（空模板不注入，节省 token）
- profile_update 的 append 模式用 `- ` 前缀追加条目，保持可读性
- 和 plan/07 的工具一起实现，共用 soul.md 指令部分
