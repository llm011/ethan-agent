"""密钥的注入与脱敏 —— 配合 ~/.ethan/.secrets/ 使用。

设计（与 docs/secrets.md 对应）：
- load_secret_env(): 把 .secrets/ 下所有 *.env 的 KEY=value 解析成 dict，
  由 shell 工具注入子进程环境，脚本里直接用 $KEY，模型上下文里从不出现明文。
- all_secret_values() / mask_text(): 安全网。shell 可被诱导 `echo $KEY`，值会回流进
  上下文，故在工具输出咽喉处把任何已知 secret 真值替换成 <secret:name> 引用。

所有函数容错：读不到 / 解析失败一律返回空或原文，绝不抛异常阻断主流程。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# .env 行：KEY=value（KEY 以字母/下划线开头）。值两侧引号在解析时去掉。
_ENV_LINE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')

# 掩码最短长度：短于此的值不参与脱敏，避免误伤正常文本/数字
_MIN_MASK_LEN = 8

# mask_text 在每次工具输出回流时都会调一次（热路径）。读+正则解析 .secrets/ 下所有文件
# 太贵，故按文件 (路径, mtime, size) 签名缓存解析结果；签名变了才重扫。
_values_cache: tuple[tuple, dict[str, str]] | None = None  # (signature, {value: name})


def _secrets_dir() -> Path:
    from ethan.core.config import CONFIG_DIR
    return CONFIG_DIR / ".secrets"


def _strip_quotes(v: str) -> str:
    v = v.strip()
    # 去掉行尾注释前先不处理（值里可能含 #），仅去成对引号
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _ENV_LINE.match(s)
        if not m:
            continue
        key, raw = m.group(1), m.group(2)
        val = _strip_quotes(raw)
        if val:
            out[key] = val
    return out


def _slugify(name: str) -> str:
    """文件名 slug：小写，_ → -。"""
    return name.lower().replace("_", "-")


def _deslugify(slug: str) -> str:
    """逆操作：大写，- → _。"""
    return slug.upper().replace("-", "_")


def _parse_single_value_file(path: Path) -> dict[str, str]:
    """解析单值密钥文件（非 .env）。

    新格式：KEY=value（KEY = deslugify(文件名)）→ 返回 {KEY: value}。
    旧格式：整个文件内容就是值 → 返回 {}（不注入 shell env，仅 get_secret 可读）。
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return {}
    if not content:
        return {}
    expected_key = _deslugify(path.name)
    prefix = f"{expected_key}="
    if content.startswith(prefix):
        val = content[len(prefix):].strip()
        if val:
            return {expected_key: val}
    return {}


def load_secret_env() -> dict[str, str]:
    """合并 .secrets/ 下所有密钥文件的 KEY=value，供 shell 子进程注入。

    来源：① *.env 文件（多 key）；② 单值文件（新格式 KEY=value，KEY = deslugify(文件名)）。
    旧格式单值文件（原始值）不注入。
    """
    d = _secrets_dir()
    if not d.is_dir():
        return {}
    merged: dict[str, str] = {}
    try:
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix == ".env":
                merged.update(_parse_env_file(p))
            else:
                merged.update(_parse_single_value_file(p))
    except OSError:
        pass
    return merged


def _dir_signature(d: Path) -> tuple:
    """.secrets/ 下所有文件的 (路径, mtime_ns, size) 签名，stat-only，不读内容。
    任一文件增删改都会改变签名，用于判断缓存是否失效。"""
    sig: list = []
    try:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                st = p.stat()
                sig.append((str(p), st.st_mtime_ns, st.st_size))
    except OSError:
        pass
    return tuple(sig)


def _scan_secret_values() -> dict[str, str]:
    """实际扫描 .secrets/ 收集所有 secret 真值及其对应 key 名。

    返回 {value: name} 映射：
    - .env 文件：name = "文件名:KEY"（如 openai.env:OPENAI_API_KEY）
    - 单值文件（新格式 KEY=value）：name = 文件名（如 api-yuntoken），value = KEY 对应的值
    - 单值文件（旧格式原始值）：name = 文件名，value = 整个内容
    """
    items: dict[str, str] = {}
    d = _secrets_dir()
    if not d.is_dir():
        return items
    try:
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix == ".env":
                for k, v in _parse_env_file(p).items():
                    if v:
                        items[v] = f"{p.name}:{k}"
            else:
                # 单值文件：尝试 KEY=value 格式（新格式），否则整体内容当作值（旧格式）
                try:
                    content = p.read_text(encoding="utf-8", errors="replace").strip()
                except OSError:
                    continue
                if not content:
                    continue
                expected_key = _deslugify(p.name)
                prefix = f"{expected_key}="
                if content.startswith(prefix):
                    val = content[len(prefix):].strip()
                    if val:
                        items[val] = p.name
                else:
                    items[content] = p.name
    except OSError:
        pass
    return items


def all_secret_values(min_len: int = _MIN_MASK_LEN) -> list[tuple[str, str]]:
    """收集所有需脱敏的真值及其 key 名，按长度降序（先替长的，防子串残留）。

    返回 [(value, name), ...]，name 用于 mask_text 替换为 <secret:name>。
    来源：① *.env 的 value；② 非 .env 单值文件的值（新格式 KEY=value 取值部分，旧格式取整体内容）。

    mask_text 在每次工具输出回流时都会调用，是热路径。按 .secrets/ 文件签名缓存
    解析结果：签名未变直接复用，避免每次重读+正则解析所有文件。
    """
    global _values_cache
    d = _secrets_dir()
    if not d.is_dir():
        _values_cache = None
        return []

    sig = _dir_signature(d)
    if _values_cache is not None and _values_cache[0] == sig:
        items = _values_cache[1]
    else:
        items = _scan_secret_values()
        _values_cache = (sig, items)

    cleaned = [(v, n) for v, n in items.items() if len(v) >= min_len
               and not v.startswith(("http://", "https://"))]  # 公开 URL 不是 secret
    return sorted(cleaned, key=lambda x: len(x[0]), reverse=True)


def mask_text(text: str) -> str:
    """把 text 里出现的任何已知 secret 真值替换为 <secret:name> 引用。

    例如 token 值 ghp_xxx 替换为 <secret:github_pat>，让 memory/LLM 只保留引用而非真值。
    无 secret / 出错时返回原文。这是一道安全网，内层只是 str.replace，正常不该抛异常。
    一旦抛了，说明脱敏失效，必须记日志告警——否则安全控件静默失败、明文照样回流，难以察觉。
    """
    if not text:
        return text
    try:
        for val, name in all_secret_values():
            if val and val in text:
                text = text.replace(val, f"<secret:{name}>")
    except Exception:
        logger.warning("mask_text 脱敏失败，原文未脱敏放行（安全网失效）", exc_info=True)
        return text
    return text
