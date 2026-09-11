"""用户自定义斜杠命令存储。

命令保存在 ~/.ethan/commands.json，格式：
  {"name": "prompt_prefix", ...}

使用时：/name <extra> → agent 收到 "{prompt_prefix}\n{extra}"
        /name        → agent 收到 "{prompt_prefix}"
"""
from __future__ import annotations

import json
from pathlib import Path


def _commands_path() -> Path:
    from ethan.core.config import CONFIG_DIR
    return CONFIG_DIR / "commands.json"


def load_commands() -> dict[str, str]:
    """加载所有自定义命令，返回 {name: prompt} 字典。"""
    path = _commands_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_command(name: str, prompt: str) -> None:
    """保存（新增或覆盖）一条自定义命令。"""
    cmds = load_commands()
    cmds[name] = prompt
    _commands_path().write_text(
        json.dumps(cmds, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def remove_command(name: str) -> bool:
    """删除一条自定义命令，返回是否成功。"""
    cmds = load_commands()
    if name not in cmds:
        return False
    del cmds[name]
    _commands_path().write_text(
        json.dumps(cmds, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True
