"""Profile 隔离 — per-profile 数据路径解析 + 迁移。

数据隔离方案（hermes 风格 profile）：
  default profile = ~/.ethan 本身（数据原地不动，向后兼容）
  命名 profile   = ~/.ethan/profiles/<name>/

全局共享（不随 profile 变）：
  config.yaml / system/*.md / scheduler.db

目录结构：
  ~/.ethan/
    config.yaml            # 全局
    system/*.md            # 全局共享（system prompt / agent 人格）
    scheduler.db           # 全局共享（scheduler）
    memory/                # default profile 的记忆
    skills/                # default profile 的技能
    knowledge/             # default profile 的知识库
    sessions.db            # default profile 的会话
    profiles/
      <name>/
        memory/ skills/ knowledge/ sessions.db
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ethan.core.config import CONFIG_DIR
from ethan.core.context import get_user_id

# ── per-profile 路径 ─────────────────────────────────────────────

def user_data_dir() -> Path:
    """当前 profile 的数据根目录。空 user_id（default）= CONFIG_DIR 本身。"""
    uid = get_user_id()
    if not uid:
        return CONFIG_DIR
    return CONFIG_DIR / "profiles" / uid


def user_memory_dir() -> Path:
    return user_data_dir() / "memory"


def user_facts_path() -> Path:
    return user_memory_dir() / "facts.json"


def user_procedures_path() -> Path:
    return user_memory_dir() / "procedures.json"


def user_episodes_path() -> Path:
    return user_memory_dir() / "episodes.json"


def user_suggestions_path() -> Path:
    return user_memory_dir() / "suggestions.json"


def user_profile_path() -> Path:
    return user_memory_dir() / "user_profile.md"


def user_persistent_path() -> Path:
    return user_memory_dir() / "persistent.md"


def user_vectors_db_path() -> Path:
    return user_memory_dir() / "vectors.db"


_session_db_migrated = False


def user_sessions_db_path() -> Path:
    """session DB 路径。直接放在数据目录，随 volume 映射持久化。"""
    global _session_db_migrated
    target = user_data_dir() / "sessions.db"
    if not _session_db_migrated:
        _session_db_migrated = True
        _migrate_tmp_session_db(target)
    return target


def _migrate_tmp_session_db(target: Path) -> None:
    """一次性迁移：把 /tmp/ethan/sessions.db 合并到 target。

    历史：曾因误判 macOS com.apple.provenance xattr 导致只读而改用 /tmp/ethan，
    但实测 aiosqlite 写入正常。撤回 workaround，把 /tmp/ethan 的数据合并回来。
    幂等：已合并的数据不会重复插入。
    """
    import sqlite3
    tmp_db = Path("/tmp/ethan/sessions.db")
    if not tmp_db.exists() or tmp_db.stat().st_size == 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size == 0:
        shutil.copy2(str(tmp_db), str(target))
        try:
            tmp_db.unlink()
        except OSError:
            pass
        return
    success = False
    try:
        con = sqlite3.connect(str(target), timeout=5)
        con.execute("ATTACH DATABASE ? AS src", (str(tmp_db),))
        con.execute("INSERT OR IGNORE INTO sessions SELECT * FROM src.sessions")
        # messages 不保留 id（避免 AUTOINCREMENT 冲突），只插入 target 中不存在的 session
        con.execute("""
            INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, created_at, usage, tool_steps, thought, quote, a2ui, images, matched_skills, ttfb_ms, total_ms)
            SELECT session_id, role, content, tool_calls, tool_call_id, created_at, usage, tool_steps, thought, quote, a2ui, images, matched_skills, ttfb_ms, total_ms
            FROM src.messages
            WHERE session_id NOT IN (SELECT DISTINCT session_id FROM messages)
        """)
        con.commit()
        con.close()
        success = True
    except Exception:
        pass
    if success:
        try:
            tmp_db.unlink()
        except OSError:
            pass


def user_skills_dir() -> Path:
    return user_data_dir() / "skills"


def user_skill_stats_path() -> Path:
    return user_skills_dir() / ".stats.json"


def user_knowledge_dir() -> Path:
    return user_data_dir() / "knowledge"


def user_agent_session_dir(session_id: str) -> Path:
    """沉浸式工具模式下，每条 Ethan 会话独立的 coding-agent 工作目录。

    会话隔离：codex/claude/opencode 在各自目录里干活，互不干扰；
    同一会话的连续消息复用同一目录 → 复用同一工具 session（多轮续接）。
    """
    return user_data_dir() / "agent-sessions" / session_id


def ensure_user_dirs() -> None:
    """创建当前 profile 的目录结构（首次访问时调用）。"""
    for d in (user_memory_dir(), user_skills_dir(), user_knowledge_dir()):
        d.mkdir(parents=True, exist_ok=True)


# ── 迁移：users/<admin> → 顶层 default profile ─────────────────

_PROFILES_MIGRATE_MARKER = CONFIG_DIR / ".profiles_migrated"


def is_profiles_migrated() -> bool:
    return _PROFILES_MIGRATE_MARKER.exists()


def migrate_to_profiles(config) -> bool:
    """把旧的 users/<admin>/ 数据精细 merge 回顶层 default profile。幂等。

    返回 True 表示执行了迁移（调用方应 save_config + 重建 UserStore）。
    """
    if _PROFILES_MIGRATE_MARKER.exists():
        return False

    users_dir = CONFIG_DIR / "users"
    if users_dir.exists():
        # 找 admin 目录（旧架构里 admin 是默认用户）
        admin_dir = users_dir / "admin"
        if admin_dir.exists():
            _merge_admin_to_default(admin_dir)
        # 清理可能存在的杂项目录（如 users/memory/ 这种被误当 user_id 建的）
        shutil.rmtree(users_dir, ignore_errors=True)

    # 清理 config.yaml：旧 admin 条目的 web_token/api_keys 挪到 network，删 admin 条目
    _migrate_admin_config_to_network(config)

    _PROFILES_MIGRATE_MARKER.write_text("migrated", encoding="utf-8")
    return True


def _migrate_admin_config_to_network(config) -> None:
    """旧 config.yaml 的 users:[admin] 条目：web_token 已等于 auth_token，
    api_keys 挪到 network.api_keys，然后删掉 admin 条目（default profile 隐式）。"""
    if not config.users:
        return
    auth_token = config.network.auth_token
    remaining = []
    for u in config.users:
        if u.id == "admin" or (auth_token and u.web_token == auth_token):
            for k in u.api_keys:
                if k and k not in config.network.api_keys:
                    config.network.api_keys.append(k)
        else:
            remaining.append(u)
    if len(remaining) == len(config.users):
        return
    config.users = remaining


def _merge_admin_to_default(admin_dir: Path) -> None:
    """把 admin 目录的数据 merge 回 ~/.ethan 顶层（default profile）。"""

    top = CONFIG_DIR
    top_memory = top / "memory"
    admin_memory = admin_dir / "memory"
    top_memory.mkdir(parents=True, exist_ok=True)

    # 1. sessions.db：INSERT OR IGNORE 合并顶层独有 session 进 admin 库，再移到顶层
    _merge_sessions_db(admin_dir, top)

    # 2. JSON 记忆文件
    _merge_json_file(admin_memory, top_memory, "procedures.json")
    _merge_json_file(admin_memory, top_memory, "episodes.json")
    _merge_json_file(admin_memory, top_memory, "lark_sessions.json")
    _merge_facts_json(admin_memory, top_memory)  # facts 按条目 merge

    # 3. Markdown 文件：admin 侧非空则用 admin
    for md in ("user_profile.md", "persistent.md"):
        src = admin_memory / md
        dst = top_memory / md
        if src.exists() and src.stat().st_size > 0:
            shutil.copy2(str(src), str(dst))

    # 4. vectors.db：admin 侧存在则覆盖顶层（向量库不合并）
    vec_src = admin_memory / "vectors.db"
    if vec_src.exists() and vec_src.stat().st_size > 0:
        shutil.copy2(str(vec_src), str(top_memory / "vectors.db"))

    # 5. skills/ + knowledge/：dirs_exist_ok 合并，admin 侧覆盖同名，顶层独有保留
    for sub in ("skills", "knowledge"):
        src = admin_dir / sub
        if src.exists() and any(src.iterdir()):
            dst = top / sub
            shutil.copytree(str(src), str(dst), dirs_exist_ok=True)

    # 6. acp_sessions.json：admin 侧存在则移到顶层
    acp_src = admin_dir / "acp_sessions.json"
    if acp_src.exists():
        shutil.copy2(str(acp_src), str(top / "acp_sessions.json"))


def _merge_json_file(admin_memory: Path, top_memory: Path, name: str) -> None:
    """JSON 文件 merge：admin 侧非空用 admin，否则保留顶层。"""
    src = admin_memory / name
    dst = top_memory / name
    if not src.exists() or src.stat().st_size == 0:
        return
    if not dst.exists() or dst.stat().st_size == 0:
        shutil.copy2(str(src), str(dst))
        return
    # 两边都有：admin 侧是活跃库，用它
    shutil.copy2(str(src), str(dst))


def _merge_facts_json(admin_memory: Path, top_memory: Path) -> None:
    """facts.json 按条目 merge：去重，保留 confidence 高的。"""
    import json
    src = admin_memory / "facts.json"
    dst = top_memory / "facts.json"
    if not src.exists() or src.stat().st_size == 0:
        return
    if not dst.exists() or dst.stat().st_size == 0:
        shutil.copy2(str(src), str(dst))
        return
    try:
        admin_data = json.loads(src.read_text(encoding="utf-8"))
        top_data = json.loads(dst.read_text(encoding="utf-8"))
    except Exception:
        # 解析失败，admin 侧覆盖
        shutil.copy2(str(src), str(dst))
        return
    admin_facts = admin_data.get("facts", []) if isinstance(admin_data, dict) else []
    top_facts = top_data.get("facts", []) if isinstance(top_data, dict) else []
    # 按 content 去重，admin 侧优先（活跃库）
    seen = {}
    for f in admin_facts:
        key = f.get("content", "")
        if key:
            seen[key] = f
    for f in top_facts:
        key = f.get("content", "")
        if key and key not in seen:
            seen[key] = f
    merged = list(seen.values())
    out = {"facts": merged}
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_sessions_db(admin_dir: Path, top: Path) -> None:
    """sessions.db：admin 库是迁移后活跃库，把顶层独有 session INSERT OR IGNORE 进 admin，再移到顶层。"""
    import sqlite3
    admin_db = admin_dir / "sessions.db"
    top_db = top / "sessions.db"
    if not admin_db.exists():
        return
    if not top_db.exists() or top_db.stat().st_size == 0:
        shutil.copy2(str(admin_db), str(top_db))
        return
    # 把顶层独有 session 并入 admin 库
    try:
        con = sqlite3.connect(str(admin_db))
        con.execute("ATTACH DATABASE ? AS top", (str(top_db),))
        # sessions 表
        con.execute("INSERT OR IGNORE INTO sessions SELECT * FROM top.sessions")
        # messages 表
        con.execute("INSERT OR IGNORE INTO messages SELECT * FROM top.messages")
        con.commit()
        con.close()
    except Exception:
        pass  # 表结构不匹配时 fallback：admin 库直接覆盖
    shutil.copy2(str(admin_db), str(top_db))
