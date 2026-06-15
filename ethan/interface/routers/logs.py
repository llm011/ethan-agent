"""logs 路由：读取后端/前端日志。"""
from pathlib import Path
from fastapi import APIRouter, Depends
from .deps import verify_token

router = APIRouter()

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


@router.get("/logs", dependencies=[Depends(verify_token)])
async def get_logs(type: str = "backend", lines: int = 500, q: str | None = None):
    log_file = _PROJECT_ROOT / ".run" / f"{type}.log"
    if not log_file.exists():
        return {"content": f"Log file not found: {log_file}"}
    try:
        all_lines = log_file.read_text(encoding="utf-8").splitlines(keepends=True)
        if q:
            all_lines = [l for l in all_lines if q.lower() in l.lower()]
        return {"content": "".join(all_lines[-lines:] if lines > 0 else all_lines)}
    except Exception as e:
        return {"content": f"Error reading log: {e}"}
