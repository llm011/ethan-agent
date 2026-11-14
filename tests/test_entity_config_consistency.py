r"""前端 entity_type 配置与后端产出的一致性测试。

## 背景（实测白屏）

`swimlane-diagram.tsx` 里：

    const cfg = ENTITY_CONFIG[et] ?? ENTITY_CONFIG.builtin;
    style={{ backgroundColor: cfg.color }}     // et 未知 → cfg undefined → 崩

报错：`Cannot read properties of undefined (reading 'color')`，整页白屏。

触发条件：多内核接入后 `ToolEvent.entity_type` 出了新值 `acp` / `dsh` / `pi`，
而 `ENTITY_CONFIG` 只有 file/system/knowledge/search/connect 五项，且**连 `builtin`
这个兜底项都没有**。

这个测试锁两件事：
  1. `builtin` 兜底项必须存在（否则任何未知类型都会崩）
  2. 后端会产出的所有 entity_type，前端都要有对应配置（或明确走 builtin）
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWIMLANE = ROOT / "packages/shared/src/components/swimlane-diagram.tsx"


def _entity_keys() -> set[str]:
    """从 ENTITY_CONFIG 里提取所有 key。"""
    src = SWIMLANE.read_text(encoding="utf-8")
    m = re.search(r"const ENTITY_CONFIG[^{]*\{(.*?)\n\};", src, re.S)
    assert m, "没找到 ENTITY_CONFIG 定义"
    return set(re.findall(r"^\s*([a-z_]+):\s*\{", m.group(1), re.M))


def test_builtin_fallback_exists():
    """`builtin` 是兜底项，缺了就会在未知 entity_type 上白屏。"""
    assert "builtin" in _entity_keys(), (
        "ENTITY_CONFIG 缺少 builtin 兜底项——任何未知 entity_type 都会抛 "
        "Cannot read properties of undefined (reading 'color') 并白屏"
    )


def test_kernel_entity_types_are_configured():
    """后端多内核产出的 entity_type 都要有配置。"""
    keys = _entity_keys()
    for kernel_entity in ("acp", "dsh", "pi"):
        assert kernel_entity in keys, (
            f"entity_type={kernel_entity!r} 未配置——有工具调用的会话会白屏"
        )


def test_existing_entity_types_still_present():
    """原有类型不能因为改动被删掉。"""
    keys = _entity_keys()
    for old in ("file", "system", "knowledge", "search", "connect"):
        assert old in keys


def test_every_key_has_label_and_color():
    """每个配置项都必须有 label 与 color，否则渲染时取到 undefined。"""
    src = SWIMLANE.read_text(encoding="utf-8")
    m = re.search(r"const ENTITY_CONFIG[^{]*\{(.*?)\n\};", src, re.S)
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        assert "label:" in line and "color:" in line, f"配置项不完整：{line}"
