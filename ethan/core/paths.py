"""多用户隔离 — per-user 数据路径解析 + 迁移。

数据隔离方案：per-user 目录 + per-user SQLite 文件（文件级天然隔离，零跨用户泄漏风险）。

目录结构：
  ~/.ethan/
    config.yaml            # 全局
    system/*.md            # 全局共享（system prompt）
    scheduler.db           # 全局共享（scheduler）
    users/
      .migrated            # 迁移幂等标记
      <user_id>/
        memory/{facts,procedures,episodes}.json + user_profile.md + vectors.db
        skills/
        knowledge/
        sessions.db
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ethan.core.config import CONFIG_DIR


# ── per-user 路径 ────────────────────────────────────────────────

def user_data_dir(user_id: str) -> Path:
    return CONFIG_DIR / "users" / user_id


def user_memory_dir(user_id: str) -> Path:
    return user_data_dir(user_id) / "memory"


def user_facts_path(user_id: str) -> Path:
    return user_memory_dir(user_id) / "facts.json"


def user_procedures_path(user_id: str) -> Path:
    return user_memory_dir(user_id) / "procedures.json"


def user_episodes_path(user_id: str) -> Path:
    return user_memory_dir(user_id) / "episodes.json"


def user_profile_path(user_id: str) -> Path:
    return user_memory_dir(user_id) / "user_profile.md"


def user_persistent_path(user_id: str) -> Path:
    return user_memory_dir(user_id) / "persistent.md"


def user_vectors_db_path(user_id: str) -> Path:
    return user_memory_dir(user_id) / "vectors.db"


def user_sessions_db_path(user_id: str) -> Path:
    return user_data_dir(user_id) / "sessions.db"


def user_skills_dir(user_id: str) -> Path:
    return user_data_dir(user_id) / "skills"


def user_skill_stats_path(user_id: str) -> Path:
    return user_skills_dir(user_id) / ".stats.json"


def user_knowledge_dir(user_id: str) -> Path:
    return user_data_dir(user_id) / "knowledge"


def ensure_user_dirs(user_id: str) -> None:
    """创建 per-user 目录结构（首次访问时调用）。"""
    for d in (user_memory_dir(user_id), user_skills_dir(user_id), user_knowledge_dir(user_id)):
        d.mkdir(parents=True, exist_ok=True)


# ── 迁移 ─────────────────────────────────────────────────────────

_MIGRATE_MARKER = CONFIG_DIR / "users" / ".migrated"


def is_migrated() -> bool:
    return _MIGRATE_MARKER.exists()


def migrate_to_multiuser() -> None:
    """将现有全局数据迁移到第一个 admin 用户的 per-user 目录。幂等。

    原始文件保留不删（留作备份）。已迁移（标记存在）则直接跳过。
    """
    if _MIGRATE_MARKER.exists():
        return

    from ethan.core.users import get_user_store
    user_store = get_user_store()
    admin_id = user_store.get_admin_user_id()

    ensure_user_dirs(admin_id)
    admin_dir = user_data_dir(admin_id)

    # 文件型记忆数据：memory/*.json, *.md, vectors.db, lark_sessions.json
    global_memory = CONFIG_DIR / "memory"
    _FILE_COPIES = [
        ("facts.json", "memory/facts.json"),
        ("procedures.json", "memory/procedures.json"),
        ("episodes.json", "memory/episodes.json"),
        ("user_profile.md", "memory/user_profile.md"),
        ("persistent.md", "memory/persistent.md"),
        ("vectors.db", "memory/vectors.db"),
        ("lark_sessions.json", "memory/lark_sessions.json"),
    ]
    for src_name, dst_rel in _FILE_COPIES:
        src = global_memory / src_name
        if src.exists():
            dst = admin_dir / dst_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))

    # 目录型数据：skills/, knowledge/
    for sub in ("skills", "knowledge"):
        src = CONFIG_DIR / sub
        if src.exists() and any(src.iterdir()):
            dst = admin_dir / sub
            shutil.copytree(str(src), str(dst), dirs_exist_ok=True)

    # sessions.db
    sessions_src = CONFIG_DIR / "sessions.db"
    if sessions_src.exists():
        shutil.copy2(str(sessions_src), str(admin_dir / "sessions.db"))

    # api_keys.db → admin 的 api_keys（写进 config.yaml）
    _migrate_api_keys_to_config(admin_id)

    _MIGRATE_MARKER.write_text("migrated", encoding="utf-8")


def _migrate_api_keys_to_config(admin_id: str) -> None:
    """读取 api_keys.db 中的 key，写入 config.yaml admin 用户的 api_keys 列表。"""
    import asyncio
    import aiosqlite

    api_keys_db = CONFIG_DIR / "api_keys.db"
    if not api_keys_db.exists():
        return

    async def _read_keys() -> list[str]:
        db = await aiosqlite.connect(str(api_keys_db))
        try:
            async with db.execute("SELECT key FROM api_keys") as cur:
                rows = await cur.fetchall()
        finally:
            await db.close()
        return [r[0] for r in rows]

    try:
        keys = asyncio.run(_read_keys())
    except Exception:
        keys = []
    if not keys:
        return

    from ethan.core.config import get_config, save_config
    from ethan.core.users import reset_user_store
    config = get_config()
    admin = next((u for u in config.users if u.id == admin_id), None)
    if admin is None:
        return
    for k in keys:
        if k and k not in admin.api_keys:
            admin.api_keys.append(k)
    save_config(config)
    reset_user_store()
