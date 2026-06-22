import logging
from pathlib import Path

logger = logging.getLogger(__name__)
CORRECTION_THRESHOLD = 2


async def update_skills_from_corrections(user_id: str = "") -> int:
    from ethan.skills.stats import SkillStats
    from ethan.skills.loader import load_skill_from_file
    from ethan.core.paths import user_skill_stats_path
    stats_path = user_skill_stats_path()
    stats = SkillStats(path=stats_path) if stats_path else SkillStats()
    updated = 0
    for skill_name, data in stats.all().items():
        corrections = data.get("corrections", [])
        if len(corrections) < CORRECTION_THRESHOLD:
            continue
        skill_file = _find_user_skill_file(skill_name, user_id)
        if not skill_file:
            continue
        skill = load_skill_from_file(skill_file)
        if not skill:
            continue
        new_content = await _merge_corrections(skill.content, corrections)
        if not new_content or len(new_content) < len(skill.content) * 0.5:
            continue
        skill_file.with_suffix(".md.bak").write_text(skill_file.read_text(encoding="utf-8"), encoding="utf-8")
        _write_updated_skill(skill_file, skill, new_content)
        data["corrections"] = []
        stats._save()
        updated += 1
        logger.info("[SkillUpdater] Updated skill: %s", skill_name)
    return updated


def _find_user_skill_file(skill_name: str, user_id: str = "") -> Path | None:
    from ethan.core.paths import user_skills_dir
    skills_dir = user_skills_dir()
    p = skills_dir / skill_name / "SKILL.md"
    if p.exists():
        return p
    p = skills_dir / f"{skill_name}.md"
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
        f"Skill 当前内容：\n<current_skill>\n{current_content}\n</current_skill>\n\n"
        f"用户纠正：\n<corrections>\n{corrections_text}\n</corrections>\n\n"
        "将纠正合并进 Skill，只输出更新后正文。"
    )
    try:
        provider = create_provider(cheap_model)
        resp = await provider.chat(
            [Message(role="user", content=prompt)],
            system="你是 AI Agent Skill 编辑器。",
        )
        return resp.content.strip()
    except Exception as e:
        logger.error("[SkillUpdater] merge failed: %s", e)
        return ""


def _write_updated_skill(skill_file: Path, skill, new_content: str):
    import yaml
    fm = {
        "name": skill.name,
        "description": skill.description,
        "trigger": skill.trigger,
        "fast_path": skill.fast_path,
    }
    skill_file.write_text(
        f"---\n{yaml.dump(fm, allow_unicode=True, sort_keys=False)}---\n\n{new_content}",
        encoding="utf-8",
    )
