# Skill 自进化 Layer 2：基于纠正自动更新 Skill 内容

## 背景与目标

Layer 1 已收集每个 Skill 的 `hit_count` 和 `corrections`。
本计划实现：当某个 Skill 积累了 ≥2 条纠正时，由 heartbeat 用廉价模型自动将纠正内容合并进 Skill 正文。

**前置依赖**：`plan/01-skill-evolution-stats.md` 必须先完成。

**性能影响：零。** 所有工作在 heartbeat 后台异步执行，完全不影响对话主路径。

---

## 当前代码状态

- `ethan/skills/stats.py`（Layer 1 新建）：`SkillStats.needs_update()` 判断是否积累了足够纠正
- `ethan/skills/loader.py`：`load_skill_from_file()` 读取 Skill，`skill.source` 是文件路径
- `ethan/core/heartbeat.py`：`_tick()` 定期执行，是触发 Skill 更新的合适位置
- `ethan/memory/consolidator.py`：`_infer_cheap_model()` 找到配套的廉价模型

---

## 实现方案

### 1. 新建 `ethan/skills/updater.py`

```python
"""Skill 内容自动更新器。

由 heartbeat 触发，完全在后台运行，不阻塞任何对话路径。
只更新用户 Skill（~/.ethan/skills/），不动内置 Skill。
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CORRECTION_THRESHOLD = 2


async def update_skills_from_corrections() -> int:
    """检查所有 Skill，对积累了足够纠正的 Skill 更新内容。返回更新数量。"""
    from ethan.skills.stats import SkillStats
    from ethan.skills.loader import load_skill_from_file

    stats = SkillStats()
    updated = 0

    for skill_name, data in stats.all().items():
        corrections = data.get("corrections", [])
        if len(corrections) < CORRECTION_THRESHOLD:
            continue

        skill_file = _find_user_skill_file(skill_name)
        if not skill_file:
            logger.warning("[SkillUpdater] No user skill file for: %s", skill_name)
            continue

        skill = load_skill_from_file(skill_file)
        if not skill:
            continue

        new_content = await _merge_corrections(skill.content, corrections)
        if not new_content:
            continue

        # 长度保护：新内容不能短于原内容的 50%
        if len(new_content) < len(skill.content) * 0.5:
            logger.warning("[SkillUpdater] New content too short for '%s', skipping", skill_name)
            continue

        # 写入前备份
        skill_file.with_suffix(".md.bak").write_text(
            skill_file.read_text(encoding="utf-8"), encoding="utf-8"
        )
        _write_updated_skill(skill_file, skill, new_content)

        # 清除已处理的纠正
        data["corrections"] = []
        stats._save()

        updated += 1
        logger.info("[SkillUpdater] Updated skill '%s'", skill_name)

    return updated


def _find_user_skill_file(skill_name: str) -> Path | None:
    from ethan.skills.loader import USER_SKILLS_DIR
    p = USER_SKILLS_DIR / skill_name / "SKILL.md"
    if p.exists():
        return p
    p = USER_SKILLS_DIR / f"{skill_name}.md"
    if p.exists():
        return p
    return None


async def _merge_corrections(current_content: str, corrections: list[str]) -> str:
    from ethan.core.config import get_config
    from ethan.memory.consolidator import _infer_cheap_model
    from ethan.providers.base import Message
    from ethan.providers.manager import create_provider

    cfg = get_config()
    cheap_model = _infer_cheap_model(cfg.defaults.model)
    corrections_text = "\n".join(f"- {c}" for c in corrections)

    prompt = (
        f"以下是一个 AI Agent Skill 的当前内容：\n\n"
        f"<current_skill>\n{current_content}\n</current_skill>\n\n"
        f"用户在实际使用中提出了以下纠正/改进：\n\n"
        f"<corrections>\n{corrections_text}\n</corrections>\n\n"
        "请将纠正合并进 Skill 内容，输出更新后的完整正文。\n"
        "要求：保持原有格式和结构；纠正与现有内容矛盾时以纠正为准；只输出正文，不要解释。"
    )
    try:
        provider = create_provider(cheap_model)
        resp = await provider.chat(
            [Message(role="user", content=prompt)],
            system="你是一个 AI Agent Skill 编辑器，根据用户反馈更新 Skill 内容。",
        )
        return resp.content.strip()
    except Exception as e:
        logger.error("[SkillUpdater] LLM merge failed: %s", e)
        return ""


def _write_updated_skill(skill_file: Path, skill, new_content: str) -> None:
    import yaml
    frontmatter = {
        "name": skill.name,
        "description": skill.description,
        "trigger": skill.trigger,
        "fast_path": skill.fast_path,
    }
    text = f"---\n{yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)}---\n\n{new_content}"
    skill_file.write_text(text, encoding="utf-8")
```

### 2. 修改 `ethan/core/heartbeat.py`（+5 行）

```python
async def _tick() -> None:
    logger.info("[Heartbeat] tick")
    await _consolidate_facts()
    await _run_heartbeat_md()
    await _update_skills()          # ← 新增


async def _update_skills() -> None:
    try:
        from ethan.skills.updater import update_skills_from_corrections
        updated = await update_skills_from_corrections()
        if updated:
            logger.info("[Heartbeat] Updated %d skill(s)", updated)
    except Exception:
        logger.exception("[Heartbeat] Skill update failed")
```

### 3. 可选：`POST /skills/evolve` 手动触发

在 `ethan/interface/api.py` 末尾追加：

```python
@app.post("/skills/evolve", dependencies=[Depends(verify_token)])
async def evolve_skills():
    from ethan.skills.updater import update_skills_from_corrections
    updated = await update_skills_from_corrections()
    return {"ok": True, "updated_count": updated}
```

---

## 文件改动清单

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `ethan/skills/updater.py` | **新建** | ~80 行 |
| `ethan/core/heartbeat.py` | **修改** | +5 行 |
| `ethan/interface/api.py` | **修改** | +6 行（可选） |

---

## 验证方法

```bash
# 手动写入 2 条 corrections
python3 -c "
import json, pathlib, time
p = pathlib.Path.home() / '.ethan/skills/.stats.json'
data = json.loads(p.read_text()) if p.exists() else {}
data['home-assistant'] = {'hit_count': 5, 'corrections': ['应该用 PUT 而不是 POST', '设备名称要加引号'], 'last_hit': time.time()}
p.write_text(json.dumps(data, ensure_ascii=False, indent=2))
"

# 手动触发
curl -X POST http://localhost:8900/skills/evolve \
  -H "Authorization: Bearer <token>"
# 返回 {"ok": true, "updated_count": 1}

# 检查文件更新
cat ~/.ethan/skills/home-assistant/SKILL.md
ls ~/.ethan/skills/home-assistant/*.bak   # 备份存在
```

---

## 注意事项

- 只更新用户 Skill（`~/.ethan/skills/`），内置 Skill 只读
- 写入前备份 `.md.bak`，可手动恢复
- 纠正处理后清空，`hit_count` 不动
- 廉价模型即可，成本极低（每次约 500-1000 token）
