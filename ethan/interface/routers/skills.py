"""skills 路由：Skill CRUD + evolve（per-user 隔离）。"""
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .deps import verify_token

router = APIRouter(prefix="/skills")


def _skills_dir(user_id: str):
    from ethan.core.paths import user_skills_dir
    return user_skills_dir()


@router.post("/evolve")
async def evolve_skills(user_id: str = Depends(verify_token)):
    from ethan.skills.updater import update_skills_from_corrections
    return {"ok": True, "updated_count": await update_skills_from_corrections(user_id=user_id)}


@router.get("")
async def list_skills(include_content: bool = False, user_id: str = Depends(verify_token)):
    """技能列表。

    **默认不返回 content**：技能正文是 SKILL.md 全文，167 个技能合计 ~1.5 MB。
    列表页只渲染 name/description/trigger，带上正文会让这个接口稳定慢 5–8 秒
    （实测 1.5 MB 响应），而用户点开某个技能时才需要正文。

    `include_content=true` 保留旧的完整返回，供脚本 / 兼容调用方使用。
    需要单个技能正文请用 GET /skills/{name}。
    """
    import asyncio

    from ethan.skills.registry import SkillRegistry

    def _load() -> SkillRegistry:
        """读磁盘 + 建 embedding 路由索引，全是同步 IO/CPU。

        167 个技能的 SKILL.md 要逐个读；首次（冷页缓存）实测能让**整个事件循环**
        卡 6–8 秒——期间连 /api/health 都要 6.4s。路由是 async 的，同步 IO 直接
        跑在事件循环线程里就是这个后果，必须丢线程池。
        """
        reg = SkillRegistry(user_id=user_id)
        reg.load()
        return reg

    reg = await asyncio.to_thread(_load)
    items = []
    for s in reg.all():
        item = {"name": s.name, "description": s.description, "trigger": s.trigger}
        if include_content:
            item["content"] = s.content
        items.append(item)
    return {"skills": items}


@router.get("/{name}")
async def get_skill(name: str, user_id: str = Depends(verify_token)):
    import asyncio

    from ethan.skills.registry import SkillRegistry

    # 同 list_skills：读盘是同步 IO，不能占着事件循环。
    def _load() -> SkillRegistry:
        reg = SkillRegistry(user_id=user_id)
        reg.load()
        return reg

    reg = await asyncio.to_thread(_load)
    skill = reg.get(name)
    if not skill:
        raise HTTPException(404, "Skill not found")
    return {"name": skill.name, "description": skill.description, "trigger": skill.trigger, "content": skill.content}


class SkillSaveRequest(BaseModel):
    name: str
    description: str
    trigger: list[str]
    content: str


def _sanitize_skill_name(name: str) -> str:
    """安全化技能名:只禁止路径分隔符/父目录穿越字符,保留中文等 Unicode。"""
    name = name.strip()
    # 禁止路径分隔符与穿越字符,其余 Unicode(含中文)一律保留
    cleaned = "".join(c for c in name if c not in "/\\:*?\"<>|")
    if not cleaned or cleaned in {".", ".."}:
        return ""
    return cleaned


@router.post("")
async def save_skill(req: SkillSaveRequest, user_id: str = Depends(verify_token)):
    skills_dir = _skills_dir(user_id)
    skills_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_skill_name(req.name)
    if not safe_name:
        raise HTTPException(400, "Invalid skill name")
    frontmatter = {"name": safe_name, "description": req.description, "trigger": req.trigger}
    content = f"---\n{yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)}---\n\n{req.content}"
    # 优先写入目录格式 <name>/SKILL.md(与 loader / 苏念 persona 读取路径一致),
    # 同时覆盖同名旧版单文件,避免两份不一致。
    skill_dir = skills_dir / safe_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    legacy = skills_dir / f"{safe_name}.md"
    if legacy.exists():
        legacy.unlink()
    return {"ok": True, "name": safe_name}


@router.delete("/{name}")
async def delete_skill(name: str, user_id: str = Depends(verify_token)):
    """删除 skill：支持目录格式（<name>/SKILL.md）和旧版单文件（<name>.md）。"""
    import shutil
    skills_dir = _skills_dir(user_id)
    safe_name = _sanitize_skill_name(name)
    if not safe_name or safe_name != name:
        raise HTTPException(400, "Invalid skill name")

    # 先确认 skill 确实存在（目录或单文件）
    skill_dir = skills_dir / safe_name
    skill_file = skills_dir / f"{safe_name}.md"
    if not skill_dir.exists() and not skill_file.exists():
        raise HTTPException(404, "Skill not found")

    removed = []
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
        removed.append(f"{safe_name}/")
    if skill_file.exists():
        skill_file.unlink()
        removed.append(f"{safe_name}.md")
    return {"ok": True, "removed": removed}
