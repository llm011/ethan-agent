"""computer_use 工具的特征化（characterization）测试。

锁定 ethan/tools/builtin/computer_use.py 的当前实际行为，为后续拆分该
1277 行大文件提供回归防护。**不测试真实桌面控制**（无 cua-driver / bridge），
只覆盖：
- A 类：纯逻辑（_to_webp / _bridge_enabled / _BridgeClient 焦点状态机 / ensure_focus 自动检测）
- B 类：用假的 bridge client 驱动 _run_via_bridge（参数校验 / 动作分发 / 截图解析），
  以及 _run_via_sdk 对 bridge-only 动作的拒绝

所有 bridge 相关测试都绕过真实网络：monkeypatch _get_bridge_client 返回假 client。
"""
from __future__ import annotations

import asyncio

import pytest

import ethan.tools.builtin.computer_use as cu
from ethan.tools.base import ToolResult

# 1x1 合法 PNG 的 base64（用于 _to_webp 正常路径）
_VALID_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def _reset_module_singletons(monkeypatch):
    """每个测试前重置 computer_use 的模块级单例，避免相互污染。"""
    monkeypatch.setattr(cu, "_computer", None, raising=False)
    monkeypatch.setattr(cu, "_computer_lock", None, raising=False)
    monkeypatch.setattr(cu, "_computer_init_failed", False, raising=False)
    monkeypatch.setattr(cu, "_bridge_client", None, raising=False)
    yield


# ── A 类：_to_webp ──────────────────────────────────────────────────────────

def test_to_webp_garbage_falls_back_to_png():
    """非法/无法解析成图片的 base64 → 回退 (原样输入, image/png)。

    PIL 可用时走 except 分支，PIL 不可用时走 ImportError 分支，两者结果一致。
    """
    data, media_type = cu._to_webp("not-a-real-png")
    assert data == "not-a-real-png"
    assert media_type == "image/png"


def test_to_webp_valid_png():
    """合法 PNG：PIL 可用则转 webp，不可用则回退 png。"""
    data, media_type = cu._to_webp(_VALID_PNG_B64)
    try:
        import PIL  # noqa: F401
        pil_available = True
    except ImportError:
        pil_available = False

    if pil_available:
        assert media_type == "image/webp"
        # 转码后数据应与原 PNG 不同
        assert isinstance(data, str) and data
    else:
        assert media_type == "image/png"
        assert data == _VALID_PNG_B64


# ── A 类：_bridge_enabled ────────────────────────────────────────────────────

def test_bridge_enabled_via_env(monkeypatch):
    monkeypatch.setenv("CUA_BRIDGE_HOST", "host.docker.internal")
    assert cu._bridge_enabled() is True


def test_bridge_enabled_via_dockerenv(monkeypatch):
    monkeypatch.delenv("CUA_BRIDGE_HOST", raising=False)
    monkeypatch.setattr(cu.os.path, "exists", lambda p: p == "/.dockerenv")
    assert cu._bridge_enabled() is True


def test_bridge_disabled_when_neither(monkeypatch):
    monkeypatch.delenv("CUA_BRIDGE_HOST", raising=False)
    monkeypatch.setattr(cu.os.path, "exists", lambda p: False)
    assert cu._bridge_enabled() is False


# ── A 类：_BridgeClient 焦点状态机 ───────────────────────────────────────────

def test_ensure_focus_pid_override_highest_priority():
    """pid_override 参数优先级最高，window_override 缺省时补 0。"""
    client = cu._BridgeClient("h", 1)
    client.set_focus(999, 888)  # 即便有显式焦点也应被 override 压过
    pid, wid = asyncio.run(client.ensure_focus(pid_override=42))
    assert (pid, wid) == (42, 0)
    pid, wid = asyncio.run(client.ensure_focus(pid_override=42, window_override=7))
    assert (pid, wid) == (42, 7)


def test_ensure_focus_explicit_set_focus():
    """set_focus 显式设置：ensure_focus 返回该 pid，window 缺省补 0。"""
    client = cu._BridgeClient("h", 1)
    client.set_focus(100)
    assert asyncio.run(client.ensure_focus()) == (100, 0)
    client.set_focus(100, 200)
    assert asyncio.run(client.ensure_focus()) == (100, 200)


def test_ensure_focus_auto_detect_and_cache():
    """自动检测：过滤 is_on_screen+pid，按 z_index 降序取首个并缓存。"""
    client = cu._BridgeClient("h", 1)
    calls: list[str] = []

    async def fake_call(name, arguments=None):
        calls.append(name)
        return {
            "ok": True,
            "result": {
                "structuredContent": {
                    "windows": [
                        {"pid": 1, "window_id": 11, "z_index": 1, "is_on_screen": True},
                        {"pid": 2, "window_id": 22, "z_index": 5, "is_on_screen": True},
                        {"pid": 3, "window_id": 33, "z_index": 9, "is_on_screen": False},
                    ]
                }
            },
        }

    client.call = fake_call  # type: ignore[assignment]
    pid, wid = asyncio.run(client.ensure_focus())
    # z_index=5 的可见窗口胜出（z=9 的不在屏）
    assert (pid, wid) == (2, 22)
    # 缓存命中：第二次调用不再触发 list_windows
    pid2, wid2 = asyncio.run(client.ensure_focus())
    assert (pid2, wid2) == (2, 22)
    assert calls == ["list_windows"]


def test_ensure_focus_fallback_to_any_pid_window():
    """没有可见窗口时回退到任意有 pid 的窗口。"""
    client = cu._BridgeClient("h", 1)

    async def fake_call(name, arguments=None):
        return {
            "ok": True,
            "result": {
                "structuredContent": {
                    "windows": [
                        {"pid": 7, "window_id": 70, "z_index": 2, "is_on_screen": False},
                    ]
                }
            },
        }

    client.call = fake_call  # type: ignore[assignment]
    assert asyncio.run(client.ensure_focus()) == (7, 70)


def test_ensure_focus_raises_on_list_windows_failure():
    client = cu._BridgeClient("h", 1)

    async def fake_call(name, arguments=None):
        return {"ok": False, "error": "boom"}

    client.call = fake_call  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="list_windows"):
        asyncio.run(client.ensure_focus())


def test_invalidate_focus_keeps_explicit():
    """invalidate_focus 只清自动缓存，保留 set_focus 的显式 pid。"""
    client = cu._BridgeClient("h", 1)
    client.set_focus(50, 60)
    client._focus_pid = 1  # 模拟自动缓存
    client._focus_window = 2
    client.invalidate_focus()
    assert client._focus_pid is None
    assert client._focus_window is None
    # 显式焦点仍在
    assert asyncio.run(client.ensure_focus()) == (50, 60)


def test_clear_focus_removes_explicit():
    client = cu._BridgeClient("h", 1)
    client.set_focus(50, 60)
    client.clear_focus()
    assert client._explicit_pid is None
    assert client._explicit_window is None


# ── B 类：假 bridge client 驱动 _run_via_bridge ──────────────────────────────

class FakeBridgeClient:
    """记录调用、返回预设响应的假 bridge client。"""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict | None]] = []
        self.focus_invalidated = 0
        self.set_focus_args = None

    async def ensure_focus(self, pid_override=None, window_override=None):
        return (pid_override or 111, window_override or 222)

    async def call(self, name, arguments=None):
        self.calls.append((name, arguments))
        resp = self.responses.get(name)
        if callable(resp):
            return resp(arguments)
        if resp is not None:
            return resp
        return {"ok": True, "result": {"structuredContent": {}}}

    def invalidate_focus(self):
        self.focus_invalidated += 1

    def set_focus(self, pid, window_id=None):
        self.set_focus_args = (pid, window_id)

    def clear_focus(self):
        pass


def _run_bridge(tool, fake, monkeypatch, **kwargs):
    async def fake_get_client():
        return fake

    monkeypatch.setattr(cu, "_get_bridge_client", fake_get_client)
    return asyncio.run(tool._run_via_bridge(**kwargs))


def test_bridge_click_requires_xy(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient()
    res = _run_bridge(tool, fake, monkeypatch, action="click")
    assert isinstance(res, ToolResult)
    assert res.is_error
    assert "click requires x and y" in res.content


def test_bridge_click_dispatch(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient({"click": {"ok": True}})
    res = _run_bridge(tool, fake, monkeypatch, action="click", x=10, y=20)
    assert res == "Click (10, 20)"
    # 分发到 driver 的 click 工具，带 button=left + focus 得到的 pid
    name, args = fake.calls[-1]
    assert name == "click"
    assert args == {"pid": 111, "x": 10, "y": 20, "button": "left"}


def test_bridge_double_click_dispatch(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient({"double_click": {"ok": True}})
    res = _run_bridge(tool, fake, monkeypatch, action="double_click", x=1, y=2)
    assert res == "Double Click (1, 2)"
    assert fake.calls[-1][0] == "double_click"


def test_bridge_click_driver_error(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient({"click": {"ok": False, "error": "no window"}})
    res = _run_bridge(tool, fake, monkeypatch, action="click", x=1, y=2)
    assert res.is_error
    assert "click 失败" in res.content
    assert "no window" in res.content


def test_bridge_screenshot_new_protocol(monkeypatch):
    """新协议：图片在 result.content[] 数组，AX 文本附加到 content。"""
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient({
        "get_window_state": {
            "ok": True,
            "result": {
                "content": [
                    {"type": "image", "data": "raw-b64"},
                    {"type": "text", "text": "button A"},
                ]
            },
        }
    })
    res = _run_bridge(tool, fake, monkeypatch, action="screenshot")
    assert isinstance(res, ToolResult)
    assert not res.is_error
    assert res.images and res.images[0]["data"] == "raw-b64"
    # "raw-b64" 不是合法 PNG → _to_webp 回退 png
    assert res.images[0]["media_type"] == "image/png"
    assert "Screenshot taken." in res.content
    assert "button A" in res.content


def test_bridge_screenshot_old_protocol(monkeypatch):
    """旧协议：图片在 structuredContent.screenshot_png_b64。"""
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient({
        "get_window_state": {
            "ok": True,
            "result": {"structuredContent": {"screenshot_png_b64": "old-b64"}},
        }
    })
    res = _run_bridge(tool, fake, monkeypatch, action="screenshot")
    assert res.images and res.images[0]["data"] == "old-b64"


def test_bridge_screenshot_empty_is_error(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient({
        "get_window_state": {"ok": True, "result": {"content": []}}
    })
    res = _run_bridge(tool, fake, monkeypatch, action="screenshot")
    assert res.is_error
    assert "截图返回为空" in res.content


def test_bridge_screenshot_call_failure(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient({
        "get_window_state": {"ok": False, "error": "perm denied"}
    })
    res = _run_bridge(tool, fake, monkeypatch, action="screenshot")
    assert res.is_error
    assert "截图失败" in res.content
    assert "perm denied" in res.content


def test_bridge_get_screen_size(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient({
        "get_screen_size": {
            "ok": True,
            "result": {"structuredContent": {"width": 100, "height": 200}},
        }
    })
    res = _run_bridge(tool, fake, monkeypatch, action="get_screen_size")
    assert res == "Screen size: 100×200"


def test_bridge_scroll_horizontal_rejected(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient()
    res = _run_bridge(tool, fake, monkeypatch, action="scroll", x=1, y=2, direction="left")
    assert res.is_error
    assert "Horizontal scroll" in res.content


def test_bridge_set_focus(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient()
    res = _run_bridge(tool, fake, monkeypatch, action="set_focus", pid=321, window_id=654)
    assert res == "Set focus to pid=321, window_id=654"
    assert fake.set_focus_args == (321, 654)


def test_bridge_set_focus_requires_pid(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient()
    res = _run_bridge(tool, fake, monkeypatch, action="set_focus")
    assert res.is_error
    assert "set_focus requires pid" in res.content


def test_bridge_launch_invalidates_focus(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient({"launch_app": {"ok": True}})
    res = _run_bridge(tool, fake, monkeypatch, action="launch", target="Safari")
    assert res == "Launched: Safari"
    assert fake.focus_invalidated == 1


def test_bridge_list_windows_filters(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient({
        "list_windows": {
            "ok": True,
            "result": {
                "structuredContent": {
                    "windows": [
                        {"pid": 1, "window_id": 11, "title": "Safari", "z_index": 1, "is_on_screen": True},
                        {"pid": 2, "window_id": 22, "title": "Notes", "z_index": 2, "is_on_screen": True},
                        {"pid": 3, "window_id": 33, "title": "Hidden", "z_index": 3, "is_on_screen": False},
                    ]
                }
            },
        }
    })
    # visible_only 默认过滤掉 is_on_screen=False，title_filter 再筛 Safari
    res = _run_bridge(
        tool, fake, monkeypatch,
        action="list_windows", visible_only=True, title_filter="safari",
    )
    assert "Found 1 window(s):" in res
    assert "pid=1" in res
    assert "Hidden" not in res
    assert "Notes" not in res


def test_bridge_unknown_action(monkeypatch):
    tool = cu.ComputerUseTool()
    fake = FakeBridgeClient()
    res = _run_bridge(tool, fake, monkeypatch, action="no_such_action")
    assert res.is_error
    assert "Unknown action" in res.content


def test_bridge_client_init_failure_returns_error(monkeypatch):
    tool = cu.ComputerUseTool()

    async def failing_get_client():
        raise RuntimeError("bridge down")

    monkeypatch.setattr(cu, "_get_bridge_client", failing_get_client)
    res = asyncio.run(tool._run_via_bridge(action="screenshot"))
    assert res.is_error
    assert "bridge down" in res.content


# ── B 类：_run_via_sdk 对 bridge-only 动作的拒绝 ─────────────────────────────

@pytest.mark.parametrize("action", sorted(cu._SDK_UNSUPPORTED))
def test_sdk_rejects_bridge_only_actions(action):
    tool = cu.ComputerUseTool()
    res = asyncio.run(tool._run_via_sdk(action=action))
    assert isinstance(res, ToolResult)
    assert res.is_error
    assert "not supported in SDK mode" in res.content


def test_sdk_unsupported_frozenset_contents():
    """锁定 bridge-only 动作清单，拆分时不得意外改动。"""
    assert cu._SDK_UNSUPPORTED == frozenset({
        "list_windows", "list_apps", "set_focus", "activate_window",
        "hide_app", "minimize_window", "kill_app", "get_cursor_position",
        "set_value", "get_accessibility_tree", "zoom", "check_permissions",
    })
