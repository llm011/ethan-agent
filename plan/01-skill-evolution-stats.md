# Skill 自进化 Layer 1：执行统计与纠正记录

## 背景与目标

当前 Skill 是静态 `.md` 文件，被触发后没有任何反馈回路。无法知道哪个 Skill
被使用了多少次、用户是否满意、是否有过纠正。

本计划实现：
- 每次 Skill 命中时，异步记录 `hit_count`
- 当用户纠正 Agent 行为且该行为与某个 Skill 有关时，记录纠正内容
- 为 Layer 2（自动更新 Skill 内容）提供数据基础

**性能影响：极低。** 统计写入通过 `asyncio.create_task` fire-and-forget，不阻塞对话。

---

## 当前代码状态

- `ethan/skills/loader.py`：`Skill` dataclass，字段有 `name/description/trigger/content/source/builtin/fast_path`，无统计字段
- `ethan/skills/registry.py`：`SkillRegistry.match()` 触发匹配，`build_context()` 注入 prompt，无命中记录
- `ethan/memory/procedures.py`：`ProcedureStore` 检测纠正信号，写入 `procedures.json`，但与 Skill 没有关联

---

## 实现方案

### 1. 新建 `ethan/skills/stats.py`

```python
"""Skill 执行统计存储。

文件位置：~/.ethan/skills/.stats.json
格式：{ "skill_name": { "hit_count": N, "corrections": ["...", ...], "last_hit": timestamp } }
"""
import json
import time
from pathlib import Path
from ethan.core.config import CONFIG_DIR

STATS_FILE = CONFIG_DIR / "skills" / ".stats.json"


class SkillStats:
    def __init__(self, path: Path = STATS_FILE):
        self._path = path
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def record_hit(self, skill_name: str) -> None:
        entry = self._data.setdefault(skill_name, {"hit_count": 0, "corrections": [], "last_hit": 0})
        entry["hit_count"] += 1
        entry["last_hit"] = time.time()
        self._save()

    def record_correction(self, skill_name: str, correction: str) -> None:
        entry = self._data.setdefault(skill_name, {"hit_count": 0, "corrections": [], "last_hit": 0})
        if correction not in entry["corrections"]:
            entry["corrections"].append(correction)
        self._save()

    def get(self, skill_name: str) -> dict:
        return self._data.get(skill_name, {"hit_count": 0, "corrections": [], "last_hit": 0})

    def all(self) -> dict:
        return dict(self._data)

    def needs_update(self, skill_name: str, correction_threshold: int = 2) -> bool:
        return len(self.get(skill_name)["corrections"]) >= correction_threshold
```

### 2. 修改 `ethan/skills/registry.py`

在 `SkillRegistry.__init__` 里初始化 `SkillStats`，并新增三个方法：

```python
from ethan.skills.stats import SkillStats

class SkillRegistry:
    def __init__(self):
        self._skills: list[Skill] = []
        self._stats = SkillStats()       # 新增

    def record_hit(self, skill_name: str) -> None:
        """记录 Skill 命中。在 Agent 完成响应后 fire-and-forget 调用。"""
        self._stats.record_hit(skill_name)

    def record_correction(self, skill_name: str, correction: str) -> None:
        self._stats.record_correction(skill_name, correction)

    def skills_needing_update(self, threshold: int = 2) -> list[str]:
        return [
            name for name in self._stats.all()
            if self._stats.needs_update(name, threshold)
        ]
```

### 3. 修改 `ethan/core/agent.py`

在 `Agent` 类里暴露 `last_matched_skills`：

```python
def __init__(self, ...):
    # 现有代码不变，新增：
    self.last_matched_skills: list[str] = []

def _build_system(self, messages, fast=False):
    # 在 Skill 匹配部分，记录命中的 skill 名：
    last_user = self._get_last_user_text(messages)
    if self._skills and last_user:
        self.last_matched_skills = []          # 每轮重置
        matched = self._skills.match(last_user)
        self.last_matched_skills = [s.name for s in matched]
        skill_ctx = self._skills.build_context(last_user)
        ...
```

### 4. 在 REPL/API 对话完成后异步记录命中

`ethan/interface/repl.py`（对话完成、`full` 非空时）：

```python
if full and agent._skills and agent.last_matched_skills:
    import asyncio
    for _skill_name in agent.last_matched_skills:
        asyncio.create_task(
            asyncio.to_thread(agent._skills.record_hit, _skill_name)
        )
```

`ethan/interface/api.py` 的 `_stream_response` 完成后同样添加（用 `asyncio.create_task`）。

---

## 文件改动清单

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `ethan/skills/stats.py` | **新建** | ~50 行 |
| `ethan/skills/registry.py` | **修改** | +10 行 |
| `ethan/core/agent.py` | **修改** | +5 行 |
| `ethan/interface/repl.py` | **修改** | +5 行 |
| `ethan/interface/api.py` | **修改** | +5 行 |

---

## 验证方法

```bash
# 1. 触发一条能命中 Skill 的消息，然后检查：
cat ~/.ethan/skills/.stats.json
# 应出现对应 skill 的 hit_count: 1

# 2. 发送纠正消息后，corrections 里应有记录
```

---

## 注意事项

- `last_matched_skills` 每次 `_build_system` 调用时重置，不会跨轮污染
- stats 文件用 `.` 前缀隐藏，避免被 `load_all_skills()` 扫描误读
- `record_hit` 用 `asyncio.to_thread` 包装，JSON 写入在线程池执行，不阻塞 event loop
