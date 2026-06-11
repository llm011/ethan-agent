"""持久记忆 — 跨 session 的长期 key facts 存储。

简单的文件存储，保存在 ~/.ethan/memory/persistent.md。
"""
from pathlib import Path

from ethan.core.config import CONFIG_DIR

PERSISTENT_FILE = CONFIG_DIR / "memory" / "persistent.md"


def load_persistent() -> str:
    """加载持久记忆内容。"""
    if PERSISTENT_FILE.exists():
        return PERSISTENT_FILE.read_text(encoding="utf-8").strip()
    return ""


def save_persistent(content: str) -> None:
    """保存持久记忆内容。"""
    PERSISTENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PERSISTENT_FILE.write_text(content, encoding="utf-8")
