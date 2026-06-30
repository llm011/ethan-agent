"""用户画像 user_profile.md 的共享读写工具。

profile_update 工具(agent 主动写)与 consolidator 后台自动抽取都通过这里读写,
保证 section 体系一致;自动抽取默认走 merge(相似/矛盾则 UPDATE、新内容则 ADD),
避免把画像堆砌成重复条目。

相似/矛盾启发式镜像 ethan/memory/facts.py 的 _is_contradiction / _find_simantic,
支持中英文(字符级 + 词级重叠)。
"""
from __future__ import annotations

from pathlib import Path


# 全部 section(顺序即 user_profile.md 中的出现顺序)
SECTIONS = [
    "基础特征",        # 名字/年龄/性格/兴趣等稳定信息
    "身份与背景",
    "目标与方向",
    "工作与沟通方式",
    "心理与情绪",      # 情绪模式/压力源/什么能安抚/重要内心感受/价值观
    "个人语言与激励",
    "与 Agent 的约定",
]

SECTION_HEADER = "## "


# ── 每日 consolidation 分组（A 方案：平铺 bullet + 分区差异化压缩）──────
# 三组各用不同的压缩策略，制造层次感而不改解析器：
#   身份事实组 — 相关事实聚类归纳、层次化，去重保留所有独立事实（沉淀感）
#   情绪快照组 — 同类情绪事件聚类、高度压缩、归纳成稳定模式（快照感）
#   约定保留组 — 仅合并表达相同的、每条指令都保留
PROFILE_GROUP_IDENTITY = ["基础特征", "身份与背景", "目标与方向", "工作与沟通方式", "个人语言与激励"]
PROFILE_GROUP_EMOTION = ["心理与情绪"]
PROFILE_GROUP_AGREEMENT = ["与 Agent 的约定"]


def ensure_profile(profile_path: Path) -> str:
    """确保 user_profile.md 存在且含全部 section header,返回内容。只在文件不存在时创建,不覆盖已有。"""
    if profile_path.exists():
        return profile_path.read_text(encoding="utf-8")

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 用户画像\n"]
    for s in SECTIONS:
        lines.append(f"\n{SECTION_HEADER}{s}\n")
    content = "\n".join(lines)
    profile_path.write_text(content, encoding="utf-8")
    return content


# ── 相似/矛盾启发式(镜像 facts.py) ────────────────────────────────

_UPDATE_SIGNALS = [
    "不", "没", "non", "not", "no longer", "instead",
    "而不是", "改为", "换成", "变成", "更新为", "升级到",
    "changed", "switched", "updated", "migrated",
]


def _overlap(a: str, b: str) -> float:
    """字符级 + 词级重叠的最大值。"""
    a_l, b_l = a.lower().strip(), b.lower().strip()
    if not a_l or not b_l:
        return 0.0
    ca, cb = set(a_l), set(b_l)
    char_ov = len(ca & cb) / max(len(ca), len(cb), 1)
    wa, wb = set(a_l.split()), set(b_l.split())
    word_ov = len(wa & wb) / max(len(wa), len(wb), 1) if (wa and wb) else 0.0
    return max(char_ov, word_ov)


def _is_update(old: str, new: str) -> bool:
    """new 是否是对 old 的更新/矛盾(应 UPDATE 而非 ADD)。"""
    if old.strip() == new.strip():
        return True
    ov = _overlap(old, new)
    if ov <= 0.5:
        return False
    new_l, old_l = new.lower(), old.lower()
    for sig in _UPDATE_SIGNALS:
        if sig in new_l and sig not in old_l:
            return True
    return ov > 0.6


# ── section 解析 ──────────────────────────────────────────────────

def _locate_section(lines: list[str], section: str) -> tuple[int, int]:
    """返回 (start_idx, end_idx),基于 splitlines(keepends)。找不到返回 (-1, -1)。"""
    header = f"{SECTION_HEADER}{section}".strip()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            start_idx = i
            break
    if start_idx is None:
        return -1, -1
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if lines[i].startswith(SECTION_HEADER):
            end_idx = i
            break
    return start_idx, end_idx


def _section_bullets(content: str, section: str) -> list[str]:
    lines = content.splitlines(keepends=True)
    start_idx, end_idx = _locate_section(lines, section)
    if start_idx < 0:
        return []
    bullets = []
    for i in range(start_idx + 1, end_idx):
        s = lines[i].strip()
        if s.startswith("- "):
            bullets.append(s[2:].strip())
    return bullets


# ── 写入 ──────────────────────────────────────────────────────────

def update_profile_section(content: str, section: str, entry: str, mode: str = "merge") -> str:
    """更新某个 section,返回新内容文本(不写盘)。

    mode:
      'append'    — 追加为新 bullet
      'overwrite' — 用 entry 替换整个 section 内容
      'merge'     — (默认)与现有 bullet 相似/矛盾则替换该条(UPDATE),否则追加(ADD)
    """
    entry = entry.strip()
    if not entry:
        return content
    header = f"{SECTION_HEADER}{section}"
    lines = content.splitlines(keepends=True)

    start_idx, end_idx = _locate_section(lines, section)

    if start_idx < 0:
        # section 不存在,新建(追加到文件末尾)
        return content + f"\n{header}\n- {entry}\n"

    if mode == "overwrite":
        new_block = [lines[start_idx], f"- {entry}\n"]
        if end_idx < len(lines):
            new_block.append("\n")
        return "".join(lines[:start_idx] + new_block + lines[end_idx:])

    if mode == "merge":
        bullets = _section_bullets(content, section)
        for bidx, b in enumerate(bullets):
            if _is_update(b, entry):
                return _replace_bullet(lines, start_idx, end_idx, bidx, entry)
        # 没有相似的,落回 append
        mode = "append"

    if mode == "append":
        insert_at = end_idx
        for i in range(end_idx - 1, start_idx, -1):
            if lines[i].strip():
                insert_at = i + 1
                break
        return "".join(lines[:insert_at] + [f"- {entry}\n"] + lines[insert_at:])

    return content


def _replace_bullet(lines: list[str], start_idx: int, end_idx: int, bullet_idx: int, new_entry: str) -> str:
    """替换 section(start_idx..end_idx)下第 bullet_idx 个 bullet 行。"""
    count = 0
    for i in range(start_idx + 1, end_idx):
        if lines[i].strip().startswith("- "):
            if count == bullet_idx:
                lines[i] = f"- {new_entry.strip()}\n"
                return "".join(lines)
            count += 1
    return "".join(lines)


def merge_section_entries(content: str, section: str, entries: list[str]) -> str:
    """把多条 entry 依次 merge 进 section(对 content 文本操作,逐条去重)。供 consolidator 批量写入。"""
    for e in entries:
        if e and e.strip():
            content = update_profile_section(content, section, e, mode="merge")
    return content


def section_bullets(content: str, section: str) -> list[str]:
    """读取某 section 下的平铺 bullet 列表（公开封装，供每日 consolidation 用）。"""
    return _section_bullets(content, section)


def set_section_bullets(content: str, section: str, bullets: list[str]) -> str:
    """用 bullets 整体替换某 section 的内容，返回新文本（不写盘）。

    供每日 consolidation 写回压缩结果。bullets 为空时保持 section header 但清空条目；
    section 不存在则新建追加到文末。
    """
    clean = [b.strip() for b in bullets if b and b.strip()]
    header = f"{SECTION_HEADER}{section}"
    lines = content.splitlines(keepends=True)
    start_idx, end_idx = _locate_section(lines, section)

    body = [lines[start_idx]] if start_idx >= 0 else [f"{header}\n"]
    for b in clean:
        body.append(f"- {b}\n")
    if clean:
        body.append("\n")

    if start_idx < 0:
        return content + "\n" + "".join(body)
    return "".join(lines[:start_idx] + body + lines[end_idx:])


def write_section(profile_path: Path, section: str, entry: str, mode: str = "merge") -> None:
    """便捷封装:ensure + update + 写盘。"""
    content = ensure_profile(profile_path)
    updated = update_profile_section(content, section, entry, mode=mode)
    profile_path.write_text(updated, encoding="utf-8")


def apply_extraction(result: dict) -> None:
    """把 extract_cold() 返回里的 profile_psych 写进当前用户的 user_profile.md「心理与情绪」(merge 去重)。

    基础特征不在此后台写入——由用户在「我的画像」设置、或 agent 在对话中明确获知后用 profile_update 写。
    供 _maybe_consolidate(chat) 与 _background_consolidate(repl) 共用,保证两处写入逻辑一致。
    """
    psych = result.get("profile_psych") or []
    if not psych:
        return
    profile_path = _user_profile_path()
    content = ensure_profile(profile_path)
    content = merge_section_entries(content, "心理与情绪", psych)
    profile_path.write_text(content, encoding="utf-8")


def _user_profile_path() -> Path:
    """延迟 import 避免循环依赖(ethan.core.paths ↔ config)。"""
    from ethan.core.paths import user_profile_path
    return user_profile_path()
