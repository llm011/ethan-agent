# -*- coding: utf-8 -*-
"""全量校验函数体内的「延迟导入」目标名字是否真实存在。

为什么需要这个测试：模块重构时把函数搬走，如果调用方是在**函数体内**写的
`from x import y`，ruff 的 F401（未使用导入）和 F821（未定义名）都查不出来——
F401 只查模块顶层，F821 只看当前作用域的名字绑定。这类残留只有**运行到那一行**
才会炸，而异步生成器（如 `/v1/chat/completions` 的流式分支）在响应头已经发出后
才炸，对客户端表现为「200 + 正常的 SSE 头，但 body 是空的」——极难定位。

真实案例：
  - `routers/completions.py` 的 `_stream_completions` 从 `routers.chat` 导入
    `_maybe_consolidate`，而它早已迁到 `routers.tasks`，导致流式接口全挂；
  - `channels/lark/webhook.py` 从 `lark.send` 导入 `_send_reaction`，实际在
    `lark.typing`，异常直接打断整条飞书消息处理链。

这里用 AST 找出 ethan 包下所有 `ImportFrom`，逐个 resolve 目标模块并检查名字。
"""
from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

import ethan

ROOT = pathlib.Path(ethan.__file__).parent


def _module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(["ethan", *parts])


def _resolve_target(node: ast.ImportFrom, mod: str, is_pkg: bool) -> str | None:
    """把（可能是相对的）ImportFrom 解析成完整模块路径。"""
    if node.level == 0:
        return node.module
    pkg = mod if is_pkg else mod.rpartition(".")[0]
    base = pkg
    for _ in range(node.level - 1):
        base = base.rpartition(".")[0]
    if not base:
        return node.module
    return f"{base}.{node.module}" if node.module else base


def _collect_imports() -> list[tuple[pathlib.Path, int, str, str]]:
    """(文件, 行号, 目标模块, 导入名)。"""
    out: list[tuple[pathlib.Path, int, str, str]] = []
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        mod = _module_name(path)
        is_pkg = path.name == "__init__.py"
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            target = _resolve_target(node, mod, is_pkg)
            if not target or not target.startswith("ethan"):
                continue
            for alias in node.names:
                if alias.name != "*":
                    out.append((path, node.lineno, target, alias.name))
    return out


def _missing() -> list[str]:
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for path, lineno, target, name in _collect_imports():
        try:
            module = importlib.import_module(target)
        except Exception as exc:  # noqa: BLE001 — 模块本身导不进来，直接报
            key = (target, name)
            if key not in seen:
                seen.add(key)
                problems.append(
                    f"{path.relative_to(ROOT)}:{lineno} from {target} import {name} "
                    f"-> 模块导入失败: {exc!r}"
                )
            continue
        if hasattr(module, name):
            continue
        # `from pkg import submodule` 是合法的，名字在模块上不存在
        try:
            importlib.import_module(f"{target}.{name}")
        except Exception:  # noqa: BLE001
            key = (target, name)
            if key not in seen:
                seen.add(key)
                problems.append(
                    f"{path.relative_to(ROOT)}:{lineno} from {target} import {name} "
                    f"-> name not found"
                )
    return problems


def test_all_ethan_import_targets_exist():
    """ethan 包内所有（含函数体内的）导入目标都必须真实存在。"""
    problems = _missing()
    assert not problems, (
        "以下导入目标不存在，运行时会在那一行抛 ImportError：\n"
        + "\n".join(f"  {p}" for p in problems)
    )
