r"""外部内核 session id 的展示 / 持久化契约。

## 需求

用户原话：「如果用的是非 ethan 内核，我希望能在对话顶部的标题下面展示这个对话的
session id，它是 dsh 的 或 claude code 的 session id，并且后面另个小复制按钮，
这样就可以在命令里定位到具体的对话」。

## 两个 id 必须分开

`KernelRequest.session_id` 是 **Ethan 自己的**会话 id（落库主键、续接依据）。
外部内核建立连接后会产生自己的 id（DSH 的 UUID / Pi 的 `--session`），
它**绝不能覆盖** `session_id`——否则「续接哪个 Ethan 会话」就丢了。

所以有独立的 `kernel_session_id` 字段。这里锁死这条边界。

## 展示条件

只在用外部内核时展示。原生内核下 Ethan 的会话 id 对用户没有命令行价值，
多显示一行是纯噪声。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ── 字段隔离 ─────────────────────────────────────────────────


def test_kernel_request_has_separate_field():
    """`kernel_session_id` 必须与 `session_id` 是不同字段。"""
    from ethan.kernel.runtime import KernelRequest

    req = KernelRequest(session_id="s_ethan_1", kernel_session_id="dsh-uuid")
    assert req.session_id == "s_ethan_1"
    assert req.kernel_session_id == "dsh-uuid"


def test_pi_does_not_overwrite_ethan_session():
    """Pi 写自己的 id 时不能动 Ethan 的。"""
    from ethan.kernel.pi_kernel import PiKernel
    from ethan.kernel.runtime import KernelRequest

    req = KernelRequest(session_id="s_ethan_2")
    PiKernel()._handle_event({"type": "session", "id": "pi-uuid-1"}, req)
    assert req.session_id == "s_ethan_2"
    assert req.kernel_session_id == "pi-uuid-1"


def test_runner_exposes_kernel_session_id():
    """runner 要有这个字段供 producers 取用。

    它是 `__init__` 里赋值的实例属性，不在类 `dir()` 里，
    所以查源码而不是 dir —— 重点是确认这个钩子还在。
    """
    src = (ROOT / "ethan/kernel/dispatch.py").read_text(encoding="utf-8")
    assert "self.kernel_session_id" in src
    # 必须从 request 的独立字段同步（不是 request.session_id）
    assert "request.kernel_session_id" in src


# ── 持久化 ───────────────────────────────────────────────────


def test_session_model_has_kernel_fields():
    from ethan.memory.session import Session

    s = Session(id="s1", title="t", model="m", created_at=0, updated_at=0)
    assert s.kernel_session_id == ""
    assert s.kernel_kind == ""


def test_store_has_save_method():
    """落库方法存在——否则刷新页面后 id 就丢了。"""
    from ethan.memory.session import SessionStore

    assert hasattr(SessionStore, "save_kernel_session")


def test_migration_adds_columns():
    """建表迁移里要有这两列（老库升级靠它）。"""
    src = (ROOT / "ethan/memory/session.py").read_text(encoding="utf-8")
    assert "kernel_session_id" in src
    assert "ADD COLUMN kernel_session_id" in src
    assert "ADD COLUMN kernel_kind" in src


def test_api_exposes_fields():
    """`GET /sessions/{id}` 要返回这两个字段，前端才能恢复。"""
    src = (ROOT / "ethan/interface/routers/sessions.py").read_text(encoding="utf-8")
    assert '"kernel_session_id"' in src
    assert '"kernel_kind"' in src


def test_stream_event_carries_fields():
    """done 事件里要带出去，前端在流结束时就地展示。"""
    src = (ROOT / "ethan/interface/routers/producers.py").read_text(encoding="utf-8")
    assert 'done_evt["kernel_session_id"]' in src
    assert 'done_evt["kernel_kind"]' in src


# ── 三端 UI ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "web/components/chat/chat-header.tsx",
        "desktop/src/components/chat/chat-header.tsx",
        "app/android/app/src/main/kotlin/com/ethan/agent/ui/chat/ChatScreen.kt",
    ],
)
def test_ui_shows_session_id_with_copy(path):
    """三端都要有：展示 + 复制按钮。

    复制是核心——用户要把它粘到命令行里，光看不给复制等于没做。
    """
    src = (ROOT / path).read_text(encoding="utf-8")
    assert "kernelSessionId" in src or "kernel_session_id" in src, f"{path} 没有展示逻辑"
    # 复制动作
    assert "clipboard" in src or "writeText" in src, f"{path} 没有复制动作"


def test_ui_shows_only_for_external_kernel():
    """原生内核下不展示（Ethan 自己的会话 id 对命令行没用）。"""
    for path in ("web/components/chat/chat-header.tsx", "desktop/src/components/chat/chat-header.tsx"):
        src = (ROOT / path).read_text(encoding="utf-8")
        # 条件渲染：有值才显示
        assert "{kernelSessionId &&" in src, f"{path} 缺少条件渲染"


def test_android_has_badge_component():
    src = (ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/chat/ChatScreen.kt").read_text(
        encoding="utf-8"
    )
    assert "KernelSessionBadge" in src
    assert "ContentCopy" in src, "要有复制图标"
