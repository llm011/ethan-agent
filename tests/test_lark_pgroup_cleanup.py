"""飞书事件监听器的进程组清理回归测试。

背景：`lark-cli event consume` 会再 fork 出 `event _bus` 孙子进程，真正握着飞书
长连接。飞书对「同一 app 同一 event_key」只允许一个长连接订阅者。若停止时只
terminate() 直接子进程，`_bus` 会被 init 收养成孤儿（PPID=1）继续占着订阅名额，
重启后新实例「连上了却收不到任何事件」。

修复：spawn 时 start_new_session=True（自成进程组），停止时 _terminate_proc_group()
按组 SIGTERM→超时→SIGKILL，把 consume + _bus 一起带走。

本仓库未启用 pytest-asyncio，协程用例统一走 asyncio.run()（与 test_lark_ux.py 一致）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

from ethan.interface.channels.lark.events import _terminate_proc_group

# 模拟 lark-cli：父进程（≈consume）再 fork 一个孙子（≈_bus），两者都长 sleep。
_FORK_CHILD = (
    "import os,time,sys\n"
    "cf,gf = sys.argv[1], sys.argv[2]\n"
    "pid = os.fork()\n"
    "if pid == 0:\n"
    "    open(gf,'w').write(str(os.getpid()))\n"
    "    time.sleep(300)\n"
    "else:\n"
    "    open(cf,'w').write(str(os.getpid()))\n"
    "    time.sleep(300)\n"
)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


async def _spawn_tree(child_file: str, grand_file: str):
    r_fd, w_fd = os.pipe()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", _FORK_CHILD, child_file, grand_file,
        stdin=r_fd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    os.close(r_fd)
    os.close(w_fd)
    return proc


async def _read_pid(path: str) -> int:
    for _ in range(100):
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return int(open(path).read())
        await asyncio.sleep(0.05)
    raise AssertionError(f"子/孙进程未在超时内写出 pid: {path}")


def test_terminate_proc_group_reaps_grandchild():
    """_terminate_proc_group 应杀掉子进程及其 fork 出的孙子，不留孤儿。"""

    async def _run():
        with tempfile.TemporaryDirectory() as d:
            cf, gf = os.path.join(d, "child.pid"), os.path.join(d, "grand.pid")
            proc = await _spawn_tree(cf, gf)
            child = await _read_pid(cf)
            grand = await _read_pid(gf)
            assert _alive(child) and _alive(grand)

            await _terminate_proc_group(proc)
            # 给孙子一点被收尸的时间
            for _ in range(40):
                if not _alive(grand):
                    break
                await asyncio.sleep(0.05)

            assert not _alive(child), "子进程（consume）应已被杀"
            assert not _alive(grand), "孙子进程（_bus）应已被杀，不留孤儿"

    asyncio.run(_run())


def test_terminate_proc_group_noop_on_dead_proc():
    """子进程已退出时调用应安全返回（ProcessLookupError 兜底），不抛异常。"""

    async def _run():
        r_fd, w_fd = os.pipe()
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "pass",
            stdin=r_fd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        os.close(r_fd)
        os.close(w_fd)
        await proc.wait()
        # 已退出，再清理应是 no-op，不抛
        await _terminate_proc_group(proc)

    asyncio.run(_run())


def test_terminate_proc_group_none_is_safe():
    """proc=None 时安全返回。"""
    asyncio.run(_terminate_proc_group(None))


# consume 先退、孙子 _bus 忽略 SIGTERM 赖着：验证整组仍被 SIGKILL 补刀收掉。
_STUBBORN_GRANDCHILD = (
    "import os,time,sys,signal\n"
    "cf,gf = sys.argv[1], sys.argv[2]\n"
    "pid = os.fork()\n"
    "if pid == 0:\n"
    "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"  # 孙子无视 SIGTERM
    "    open(gf,'w').write(str(os.getpid()))\n"
    "    time.sleep(300)\n"
    "else:\n"
    "    open(cf,'w').write(str(os.getpid()))\n"
    "    time.sleep(0.3)\n"  # consume 很快自己退，不等孙子
)


def test_terminate_proc_group_sigkills_stubborn_grandchild():
    """consume 先退、孙子忽略 SIGTERM 时，探活整组后应 SIGKILL 补刀，不留孤儿。"""

    async def _run():
        with tempfile.TemporaryDirectory() as d:
            cf, gf = os.path.join(d, "child.pid"), os.path.join(d, "grand.pid")
            r_fd, w_fd = os.pipe()
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", _STUBBORN_GRANDCHILD, cf, gf,
                stdin=r_fd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            os.close(r_fd)
            os.close(w_fd)
            grand = await _read_pid(gf)
            await _read_pid(cf)
            assert _alive(grand)
            # 等 consume 自己退出，制造「子已死、孙还在且不理 SIGTERM」的局面
            await asyncio.sleep(0.6)

            await _terminate_proc_group(proc)
            for _ in range(40):
                if not _alive(grand):
                    break
                await asyncio.sleep(0.05)
            assert not _alive(grand), "顽固孙子应被 SIGKILL 收掉，不留孤儿"

    asyncio.run(_run())

