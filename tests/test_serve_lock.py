"""serve 单实例锁（``ethan/interface/serve_lock.py``）的回归测试。

锁要守住的只有一件事：**两个 serve 进程同时启动时，只有一个能继续往下走**。

之前的闸门都是「先查后做」——``_port_is_served`` 查的是「端口上有没有一个
**健康**的 ethan」，两次并发启动会同时查到「没有」，然后一起跑完数十秒的
lifespan，最后才在 bind 时撞 Errno 48；而 uvicorn 绑失败并不退出，于是留下
一个不监听任何端口的僵尸。锁把「检查 + 启动」变成原子区间。

另一类闸门漏掉的情况：端口上那个 ethan **卡死**了（进程在、health 超时），
``_port_is_served`` 返回 False，新实例照常通过。锁对这种情况不敏感——它只关心
「有没有另一个 serve 正在启动」，正是想要的语义。
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from ethan.interface import api, serve_lock


@pytest.fixture(autouse=True)
def _isolated_lock_dir(monkeypatch, tmp_path):
    """锁文件写到 tmp 目录，别碰真实的 /tmp/ethan。"""
    monkeypatch.setattr(serve_lock, "_DEFAULT_LOCK_DIR", tmp_path / "locks")
    import ethan.watchdog as w

    monkeypatch.setattr(w, "_PID_DIR", tmp_path / "locks")
    monkeypatch.delenv("ETHAN_NO_WATCHDOG", raising=False)
    serve_lock._reset_for_tests()
    yield
    serve_lock._reset_for_tests()


# ── acquire / release 基本语义 ───────────────────────────────────────


def test_acquire_then_acquire_again_blocks():
    ok, holder = serve_lock.acquire(8989)
    assert ok is True
    assert holder is None

    ok2, holder2 = serve_lock.acquire(8989)
    assert ok2 is False
    # 持有者 pid 是从锁文件里读的，就是本进程
    assert holder2 == os.getpid()


def test_release_lets_another_acquire_succeed():
    assert serve_lock.acquire(8989)[0] is True
    serve_lock.release()
    assert serve_lock.acquire(8989)[0] is True


def test_different_ports_do_not_block_each_other():
    assert serve_lock.acquire(8900)[0] is True
    assert serve_lock.acquire(8901)[0] is True


def test_dev_mode_buckets_by_data_dir(monkeypatch, tmp_path):
    """ETHAN_NO_WATCHDOG=1 时按数据目录分桶：不同数据目录的实例可以并存。

    多 worktree 规范明确允许「各自起实例」，那正是这个开关的用途；同一个端口 +
    同一个数据目录仍然互斥（那才是真的重复启动）。
    """
    monkeypatch.setenv("ETHAN_NO_WATCHDOG", "1")
    calls = {"n": 0}

    monkeypatch.setattr(
        serve_lock, "_data_dir_tag", lambda: (calls.__setitem__("n", calls["n"] + 1),
                                             f"dir{calls['n']}")[1]
    )
    # 同一进程内两次 acquire 用的是不同标签 → 对应两个不同数据目录
    assert serve_lock.acquire(8900)[0] is True
    assert serve_lock.acquire(8900)[0] is True


def test_lock_path_includes_tag_only_in_dev_mode(monkeypatch, tmp_path):
    monkeypatch.delenv("ETHAN_NO_WATCHDOG", raising=False)
    prod = serve_lock.lock_path(8900)
    monkeypatch.setenv("ETHAN_NO_WATCHDOG", "1")
    dev = serve_lock.lock_path(8900)
    assert prod.name == "serve-8900.lock"
    assert dev.name.startswith("serve-8900-") and dev.name.endswith(".lock")


# ── 跨进程：这才是锁真正要防的场景 ───────────────────────────────────


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_child(port: int, lock_dir: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = _REPO_ROOT
    # 让子进程用同一个锁目录（fixture 改的是本进程内的常量）
    code = (
        "import pathlib, sys\n"
        "from ethan.interface import serve_lock\n"
        f"serve_lock._DEFAULT_LOCK_DIR = pathlib.Path({lock_dir!r})\n"
        "ok, holder = serve_lock.acquire(int(sys.argv[1]))\n"
        "print('GOT' if ok else f'BLOCKED:{holder}')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code, str(port)],
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_second_process_is_blocked(tmp_path):
    """本进程持锁时，另一个进程拿不到锁并报出持有者 pid。"""
    assert serve_lock.acquire(8989)[0] is True

    proc = _run_child(8989, str(serve_lock._DEFAULT_LOCK_DIR))
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    assert out.startswith("BLOCKED:")
    assert out.split(":", 1)[1] == str(os.getpid())


def test_child_can_acquire_when_parent_released(tmp_path):
    assert serve_lock.acquire(8989)[0] is True
    serve_lock.release()

    proc = _run_child(8989, str(serve_lock._DEFAULT_LOCK_DIR))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "GOT"


def test_data_dir_tag_is_stable_across_processes():
    """同一条数据目录，不同进程算出的标签必须一致。

    回归用：初版用内置 ``hash(str)``，受 PYTHONHASHSEED 影响每进程随机化，
    两个 serve 各建一把锁、互斥直接失效（实测同时抢下同一端口）。
    """
    code = "from ethan.interface import serve_lock; print(serve_lock._data_dir_tag())"
    env = os.environ.copy()
    env["PYTHONPATH"] = _REPO_ROOT
    env["ETHAN_DATA_DIR"] = "/tmp/ethan-locktest/data"
    outs = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env=env, timeout=60).stdout.strip()
        for _ in range(2)
    }
    assert len(outs) == 1 and list(outs)[0]


def test_dev_mode_same_port_same_data_dir_still_blocks(monkeypatch):
    """ETHAN_NO_WATCHDOG=1 时分桶，但同一数据目录的重复启动仍须互斥。"""
    monkeypatch.setenv("ETHAN_NO_WATCHDOG", "1")
    monkeypatch.setenv("ETHAN_DATA_DIR", "/tmp/ethan-locktest/data")
    assert serve_lock.acquire(8900)[0] is True
    assert serve_lock.acquire(8900)[0] is False


# ── run_server 接线 ──────────────────────────────────────────────────


def test_run_server_exits_when_lock_held(monkeypatch):
    """锁被别人拿着 → run_server 立刻退出，不再做端口/DB 检查，更不碰 uvicorn。"""
    monkeypatch.setattr(api, "_port_is_served", lambda *_a, **_k: False)
    monkeypatch.setattr(api, "_find_db_conflicts", lambda: [(999, "/x/sessions.db")])
    monkeypatch.setattr(serve_lock, "acquire", lambda _p: (False, 4242))

    reached = {"port": False, "uvicorn": False}
    monkeypatch.setattr(
        api, "_port_is_served", lambda *_a, **_k: reached.__setitem__("port", True) or False
    )

    def _fake_uvicorn_run(*_a, **_k):
        reached["uvicorn"] = True

    monkeypatch.setitem(sys.modules, "uvicorn",
                        type("M", (), {"run": staticmethod(_fake_uvicorn_run)}))

    with pytest.raises(SystemExit) as exc:
        api.run_server(host="0.0.0.0", port=8900)

    assert exc.value.code == 1
    assert reached["port"] is False
    assert reached["uvicorn"] is False


def test_run_server_acquires_lock_before_start(monkeypatch):
    monkeypatch.setattr(api, "_port_is_served", lambda *_a, **_k: False)
    monkeypatch.setattr(api, "_find_db_conflicts", lambda: [])

    seen = {"lock_port": None, "uvicorn": False}

    def _acquire(port):
        seen["lock_port"] = port
        return True, None

    monkeypatch.setattr(serve_lock, "acquire", _acquire)

    def _fake_uvicorn_run(*_a, **_k):
        seen["uvicorn"] = True

    monkeypatch.setitem(sys.modules, "uvicorn",
                        type("M", (), {"run": staticmethod(_fake_uvicorn_run)}))

    api.run_server(host="0.0.0.0", port=8900)

    assert seen["lock_port"] == 8900
    assert seen["uvicorn"] is True


def test_run_server_force_skips_lock(monkeypatch):
    """`ethan serve --force` 是明确的「我知道我在干什么」，不该被锁拦。"""
    monkeypatch.setattr(api, "_port_is_served", lambda *_a, **_k: False)
    monkeypatch.setattr(api, "_find_db_conflicts", lambda: [])

    called = {"n": 0}
    monkeypatch.setattr(
        serve_lock, "acquire", lambda _p: called.__setitem__("n", called["n"] + 1) or (False, 1)
    )
    monkeypatch.setitem(sys.modules, "uvicorn",
                        type("M", (), {"run": staticmethod(lambda *_a, **_k: None)}))

    api.run_server(host="0.0.0.0", port=8900, force=True)
    assert called["n"] == 0


# ── 降级：不能因为锁机制让服务起不来 ─────────────────────────────────


def test_acquire_degrades_when_lock_file_unwritable(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setattr(serve_lock, "_DEFAULT_LOCK_DIR", blocker)

    ok, holder = serve_lock.acquire(8989)
    assert ok is True and holder is None


def test_acquire_degrades_without_fcntl(monkeypatch):
    """Windows 没有 fcntl：必须返回「拿到」，保持旧行为而不是崩。"""
    monkeypatch.setitem(sys.modules, "fcntl", None)
    ok, holder = serve_lock.acquire(8989)
    assert ok is True and holder is None
