"""secrets 工具 —— 密钥的统一存取。

密钥存到 ~/.ethan/.secrets/<name>（0600 权限），不写入 config.yaml / skills / memory 等明文位置。
读取（get_secret）需用户授权（consent），写入（set_secret）由 Agent 主动存用户提供的值。
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from ethan.tools.base import BaseTool


def _secrets_dir() -> Path:
    from ethan.core.config import CONFIG_DIR
    d = CONFIG_DIR / ".secrets"
    d.mkdir(parents=True, exist_ok=True)
    # 目录 0700
    try:
        os.chmod(d, stat.S_IRWXU)
    except OSError:
        pass
    return d


def _safe_name(name: str) -> str:
    """禁止路径穿越：只允许字母数字 _ - . /。"""
    safe = "".join(c for c in name if c.isalnum() or c in "-_./")
    safe = safe.strip("./")
    if not safe or ".." in safe:
        raise ValueError(f"invalid secret name: {name!r}")
    return safe


class SetSecretTool(BaseTool):
    fast_path = False
    cacheable = False
    name = "set_secret"
    description = (
        "把一个密钥（API key、token、密码等）安全存到 ~/.ethan/.secrets/。"
        "用户告诉你某个 key、或你生成了需要保存的凭证时调用。"
        "绝不把密钥明文写进 config.yaml / skills / memory —— 一律走这个工具。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "密钥名，按场景/功能命名，如 'openai_key'、'homeassistant_token'。字母数字 _ - . /",
            },
            "value": {
                "type": "string",
                "description": "密钥值。",
            },
        },
        "required": ["name", "value"],
    }

    async def run(self, name: str, value: str) -> str:
        try:
            safe = _safe_name(name)
        except ValueError as e:
            return f"Error: {e}"
        path = _secrets_dir() / safe
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value), encoding="utf-8")
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass
        return f"✓ 密钥已保存: {safe}（~/.ethan/.secrets/{safe}）"


class GetSecretTool(BaseTool):
    fast_path = False
    cacheable = False  # 密钥绝不缓存
    name = "get_secret"
    description = (
        "按名称读取已保存的密钥。读取需要用户授权确认。"
        "调用其它服务（Home Assistant、第三方 API）需要 key 时先取出来。"
        "不确定有哪些密钥时先调 list_secrets。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "密钥名",
            },
        },
        "required": ["name"],
    }

    def consent_check(self, name: str = "", **kwargs) -> str | None:
        return f"读取密钥: {name}"

    async def run(self, name: str) -> str:
        try:
            safe = _safe_name(name)
        except ValueError as e:
            return f"Error: {e}"
        path = _secrets_dir() / safe
        if not path.exists() or not path.is_file():
            return f"Error: 密钥不存在: {safe}（用 list_secrets 查看已有密钥）"
        return path.read_text(encoding="utf-8", errors="replace").strip()


class ListSecretsTool(BaseTool):
    fast_path = False
    cacheable = True
    name = "list_secrets"
    description = "列出已保存的密钥名（不显示值）。不确定有哪些密钥时调用。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    # 列出名称不需要授权（不泄露值）

    async def run(self) -> str:
        d = _secrets_dir()
        names = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file())
        if not names:
            return "（暂无密钥。用 set_secret 保存。）"
        return "已保存的密钥:\n" + "\n".join(f"- {n}" for n in names)
