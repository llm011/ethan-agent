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
async def list_skills(user_id: str = Depends(verify_token)):
    from ethan.skills.registry import SkillRegistry
    reg = SkillRegistry(user_id=user_id)
    reg.load()
    return {"skills": [{"name": s.name, "description": s.description, "trigger": s.trigger, "content": s.content} for s in reg.all()]}


@router.get("/{name}")
async def get_skill(name: str, user_id: str = Depends(verify_token)):
    from ethan.skills.registry import SkillRegistry
    reg = SkillRegistry(user_id=user_id)
    reg.load()
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
