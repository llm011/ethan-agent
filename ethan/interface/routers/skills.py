"""skills 路由：Skill CRUD + evolve。"""
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .deps import verify_token

router = APIRouter(prefix="/skills")


def _skills_dir():
    from ethan.skills.loader import USER_SKILLS_DIR
    return USER_SKILLS_DIR


@router.post("/evolve", dependencies=[Depends(verify_token)])
async def evolve_skills():
    from ethan.skills.updater import update_skills_from_corrections
    return {"ok": True, "updated_count": await update_skills_from_corrections()}


@router.get("", dependencies=[Depends(verify_token)])
async def list_skills():
    from ethan.skills.registry import SkillRegistry
    reg = SkillRegistry()
    reg.load()
    return {"skills": [{"name": s.name, "description": s.description, "trigger": s.trigger, "content": s.content} for s in reg.all()]}


@router.get("/{name}", dependencies=[Depends(verify_token)])
async def get_skill(name: str):
    from ethan.skills.registry import SkillRegistry
    reg = SkillRegistry()
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


@router.post("", dependencies=[Depends(verify_token)])
async def save_skill(req: SkillSaveRequest):
    skills_dir = _skills_dir()
    skills_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in req.name if c.isalnum() or c in "-_")
    if not safe_name:
        raise HTTPException(400, "Invalid skill name")
    frontmatter = {"name": safe_name, "description": req.description, "trigger": req.trigger}
    content = f"---\n{yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)}---\n\n{req.content}"
    (skills_dir / f"{safe_name}.md").write_text(content, encoding="utf-8")
    return {"ok": True, "name": safe_name}
