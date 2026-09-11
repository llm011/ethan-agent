"""知识库内部共享 helper — 路径清洗与标题去重。

跨多个后端复用（filesystem / obsidian / notion）。无内部依赖，是最底层。
"""
import re
from pathlib import Path


def _safe_subdir(tag: str) -> str | None:
    """把 tag 清洗为安全的**单级**子目录名，防路径穿越。

    只保留 [a-zA-Z0-9_-]，其余替换为 -；空或全为 . 时返回 None（落根目录）。
    保留此函数向后兼容；多层级请用 _safe_subpath。
    """
    name = re.sub(r"[^A-Za-z0-9_\-]", "-", tag).strip("-")
    if not name or name == "." or name == "..":
        return None
    return name


def _safe_subpath(tag: str) -> Path | None:
    """把带 `/` 的层级 tag 清洗为安全的**多级**相对路径（防穿越）。

    例：`work/coze/prd` → Path("work/coze/prd")，落盘成嵌套目录，与 Obsidian
    的层级标签约定打平。规则：
    - 按 `/` 分段（`\\` 也视作分隔符，Windows 路径归一）
    - 每段**保留 Unicode 字母/数字/下划线/连字符/空格**（含中文，与 Obsidian 打平），
      仅把文件系统危险字符（`/ \\ : * ? " < > | ` 及控制符）替换为 `-`，去首尾 `-`/空格
    - 空段、`.`、`..`、纯 `.` 序列跳过（防路径穿越）
    - 所有段都为空时返回 None（落根目录）
    """
    segments: list[str] = []
    for raw in re.split(r"[\\/]", str(tag)):
        # 只替换危险字符，保留 CJK 等 Unicode 文字
        name = re.sub(r'[\x00-\x1f<>:"|?*]', "-", raw)
        name = re.sub(r"-{2,}", "-", name).strip("- ")
        if not name or set(name) == {"."}:  # 空、"."、".." 等纯点段
            continue
        segments.append(name)
    if not segments:
        return None
    return Path(*segments)


def _strip_redundant_title_line(title: str, content: str) -> str:
    """Remove the first non-empty line of content if it's a heading that duplicates the title."""
    lines = content.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            heading_text = stripped.lstrip("#").strip()
            title_norm = re.sub(r"\s+", "", title.lower())
            heading_norm = re.sub(r"\s+", "", heading_text.lower())
            if title_norm and heading_norm and (
                title_norm in heading_norm or heading_norm in title_norm
                or _similarity(title_norm, heading_norm) > 0.6
            ):
                lines.pop(i)
                while i < len(lines) and not lines[i].strip():
                    lines.pop(i)
                return "\n".join(lines)
        break
    return content


def _similarity(a: str, b: str) -> float:
    """Simple character-level Jaccard similarity."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
