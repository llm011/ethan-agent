"""registry._build_router 激活判定的日志行为（核心：避免「假激活」）。

验证三道门槛：
  1) router.available  (模型文件就绪)
  2) router.build()     (LR 头可加载 + 有可路由 skill)
  3) 运行时依赖 onnxruntime/transformers/numpy 已安装（find_spec 探测）
只有三者同时满足，self._router 才非 None，并打出 [router] 已激活 日志。
"""
import importlib.util
import logging

import pytest

from ethan.skills.registry import SkillRegistry


class _FakeSkill:
    def __init__(self, name, trigger=(), modes=(), channels=()):
        self.name = name
        self.trigger = list(trigger)
        self.modes = list(modes)
        self.channels = list(channels)
        self.description = name


class _FakeRouter:
    _avail = False
    _routable: set = set()

    def __init__(self):
        self.available = _FakeRouter._avail
        self._routable = set()
        self._built = False

    def build(self, skills):
        self._routable = {s.name for s in skills if s.name in _FakeRouter._routable}
        self._built = bool(self._routable)
        return self._built


def _make(names):
    s = SkillRegistry("__test__")
    s._skills = [_FakeSkill(n) for n in names]
    return s


@pytest.fixture
def fake_router(monkeypatch):
    """替换 router 模块里的 EmbeddingRouter 与 model_present，并清空进程级缓存。"""
    monkeypatch.setattr("ethan.skills.router.EmbeddingRouter", _FakeRouter)
    monkeypatch.setattr("ethan.skills.router.model_present", lambda: _FakeRouter._avail)
    from ethan.skills.registry import _ROUTER_CACHE
    _ROUTER_CACHE.clear()  # 避免上一个用例的 router 被缓存复用，跳过判定
    _FakeRouter._avail = False
    _FakeRouter._routable = set()
    yield


@pytest.fixture
def logs():
    """捕获 ethan.skills.registry 日志（避开本机 caplog 夹具的版本冲突）。"""
    records = []
    h = logging.Handler()
    h.emit = lambda r: records.append(r)
    lg = logging.getLogger("ethan.skills.registry")
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    yield records
    lg.removeHandler(h)


def _patch_deps(monkeypatch, missing=()):
    """控制 onnxruntime/transformers/numpy 的 find_spec 返回，模拟依赖在/不在。"""
    _orig = importlib.util.find_spec

    def _fake(name, *a, **k):
        if name in ("onnxruntime", "transformers", "numpy"):
            # None=未安装；非 None（object()）=已安装
            return None if name in missing else object()
        return _orig(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", _fake)


def test_inactive_when_model_missing(logs, fake_router):
    """模型文件缺失 → 未激活，self._router=None。"""
    _FakeRouter._avail = False
    s = _make(["paper-analysis"])
    s._build_router()
    assert s._router is None
    assert any("未激活" in r.getMessage() and "模型文件缺失" in r.getMessage() for r in logs)


def test_active_when_all_ok(logs, fake_router, monkeypatch):
    """模型就绪 + 有可路由 skill + 依赖齐全 → 激活。"""
    _FakeRouter._avail = True
    _FakeRouter._routable = {"paper-analysis"}
    _patch_deps(monkeypatch, missing=())  # 依赖都"在"
    s = _make(["paper-analysis"])
    s._build_router()
    assert s._router is not None
    assert any("已激活" in r.getMessage() for r in logs)


def test_fake_active_when_deps_missing(logs, fake_router, monkeypatch):
    """模型就绪但 onnxruntime/transformers 缺失 → 判为实际不可用（warning）。"""
    _FakeRouter._avail = True
    _FakeRouter._routable = {"paper-analysis"}
    _patch_deps(monkeypatch, missing=("onnxruntime", "transformers"))
    s = _make(["paper-analysis"])
    s._build_router()
    assert s._router is None
    assert any("依赖缺失" in r.getMessage() for r in logs)
