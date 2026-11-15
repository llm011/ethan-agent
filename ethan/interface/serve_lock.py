"""serve 单实例锁：把「查一下有没有人占 → 然后启动」变成真正的互斥。

## 为什么需要它

``run_server`` / ``cli.serve_main`` / ``watchdog._start_server`` 各有一道
「启动前检测重复实例」的闸门，但每道闸门都是**先查后做**：

    慢启动路径（memory reindex 数十秒）     t0 查：没人 → 通过
    另一个守护者拉起的实例                  t0 查：没人 → 也通过
    → 两个都跑完 lifespan，最后才在 bind 时撞 Errno 48

于是出现两种烂摊子之一：

* 后到的实例绑不上端口，而 uvicorn 绑失败**不抛错也不退出**，挂成一个不监听
  任何端口、却持续占 CPU 的僵尸（还会污染 server.pid / heartbeat / 调度器）；
* 或者两个实例都起来了（不同端口），双写同一个 DELETE 模式的 sessions.db，
  表现为 ``database is locked``、前端「打开会话一直加载」。

更早的判据还漏了一类：``_port_is_served`` 只认**健康**的 ethan。端口上那个
实例卡死（进程还在、health 超时）时，新实例会一路穿透到 bind 才失败——而这
恰恰是最常见的「卡住 → 手动重启」场景。

## 做法

用 ``flock(fd, LOCK_EX | LOCK_NB)`` 对一把锁文件加**非阻塞排他锁**：

* 拿得到 → 继续启动，锁一直持有到进程退出（fd 由本模块的全局变量持有，
  进程无论怎么死，内核都会释放锁，不会留下需要手工清理的死锁）；
* 拿不到 → 说明有另一个 serve 进程正处在「已通过检查、还没绑定完端口」的
  窗口里，**立刻**以可读错误退出，而不是等到 bind 失败。

这把锁解决的是「检查与启动之间」的竞态，它**不替代**原有的端口 / DB 判据：
那些判据负责「端口上已经有一个健康的 ethan」和「别人的进程开着同一个库」，
锁负责「两个进程同时启动」。两者互补，缺一不可。

## 为什么不引入语言级依赖

``fcntl`` 是 CPython 标准库在 POSIX 上的模块（macOS / Linux 都有）。Windows
上没有，``fcntl`` import 失败时本模块降级为「永远拿得到锁」，保持旧行为——
宁可退回竞态，也不能让服务在 Windows 上根本起不来。

## 与 ``ETHAN_NO_WATCHDOG=1`` 的关系

那个开关的语义是「我在开发/测试，别管我」。多 worktree 场景下会**故意**起
第二个实例（独立数据目录、独立端口），此时若还按「同端口只能一个」加锁就
把开发流程堵死了。所以：

* 默认（生产/常驻）：按端口加锁，同一端口只能有一个 serve 在启动；
* ``ETHAN_NO_WATCHDOG=1``：按「端口 + 数据目录」加锁——不同端口或不同数据
  目录的实例互不影响，同一端口 + 同一数据目录仍然互斥（那确实是重复启动）。
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: 锁文件所在目录，与 watchdog 的 pid 目录保持一致（``/tmp/ethan``）。
_DEFAULT_LOCK_DIR = Path("/tmp/ethan")

#: 进程退出前一直持有的 fd。不能是局部变量——函数的栈一退，fd 引用计数归零，
#: 文件描述符被关闭，锁也就跟着放了，等于没加。
_HELD_FDS: list[int] = []


def _lock_dir() -> Path:
    """锁目录：优先跟随 watchdog 的 ``_PID_DIR``（测试会 monkeypatch 它）。

    直接 import ``ethan.watchdog._PID_DIR`` 会形成循环依赖（watchdog 也要用
    本模块），所以按需读属性；watchdog 尚未加载时回退默认值。
    """
    import sys

    mod = sys.modules.get("ethan.watchdog")
    pid_dir = getattr(mod, "_PID_DIR", None) if mod is not None else None
    return Path(pid_dir) if pid_dir is not None else _DEFAULT_LOCK_DIR


def _watchdog_disabled() -> bool:
    # 不用 ``watchdog.watchdog_disabled()``：那要求 watchdog 模块已加载，而本模块
    # 恰恰可能在 watchdog import 之前被 api.run_server 调用到。判据本身只有一行
    # （只认 "1"），在这里复刻比引入 import 循环靠谱。
    return os.environ.get("ETHAN_NO_WATCHDOG") == "1"


def _data_dir_tag() -> str:
    """数据目录的短哈希，用于给开发态锁文件分桶。

    只取哈希不取路径：路径里有 ``/``，直接拼进文件名会变成子目录；哈希足够
    区分不同 worktree 的数据目录，人也不用读它。

    **必须用 sha256 而不是内置 ``hash()``**：``str`` 的 ``hash()`` 受
    ``PYTHONHASHSEED`` 影响、每个进程随机化，两个进程算出不同标签就各自建了
    一把锁，互斥直接失效（实测过：两个 serve 抢同一端口都"拿到锁"）。

    取 12 位而不是 8 位：截断的唯一目的是「换个数据目录就能并存」，一旦撞了会
    表现成两个不同目录互相阻塞、报错里还是一个莫名其妙的 pid，非常难排查。
    多留 4 位几乎不增加可读成本，却把碰撞率再降 65536 倍。
    """
    try:
        from ethan.core.paths import user_data_dir

        raw = str(user_data_dir().resolve())
    except Exception:
        raw = os.environ.get("ETHAN_DATA_DIR", "") or os.path.expanduser("~/.ethan")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def lock_path(port: int) -> Path:
    """该 serve 实例对应的锁文件路径。

    「是否按数据目录分桶」的判断**只在这里**，``_data_dir_tag`` 保持成纯粹的
    路径 → 标签函数：将来若想换分桶维度（按 venv、按 profile…），改这一处即可，
    不会因为别处顺手复用它而意外触发。
    """
    dev = _watchdog_disabled()
    suffix = f"-{_data_dir_tag()}" if dev else ""
    return _lock_dir() / f"serve-{port}{suffix}.lock"


def acquire(port: int) -> tuple[bool, int | None]:
    """尝试加锁。

    返回 ``(True, None)`` 表示拿到；``(False, holder_pid)`` 表示被占，其中
    ``holder_pid`` 是从锁文件里读到的持有者 pid（可能为 None——对方还没写进去，
    或不是本程序写的；只用于给用户看的提示，不作为判据）。

    平台不支持 ``fcntl``（Windows）或锁文件建不出来时返回 ``(True, None)``，
    保持旧行为。这两种降级会打日志：``fcntl`` 缺失是 info（启动时打一次就够），
    锁文件不可写是 warning（环境异常，值得排查）。
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - 仅在 Windows 上走到
        # info 而不是 debug：这时单实例保护是**真的没有**，排查并发启动问题时
        # 必须能在日志里看到这一行，否则会误以为锁生效了。
        logger.info("[ServeLock] 当前平台无 fcntl，单实例锁未启用")
        return True, None

    path = lock_path(port)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        # 锁文件都建不出来（/tmp 只读、权限异常）：不因为一个防御性机制让服务
        # 起不来，退回旧行为并留一条 warning 供排查。
        logger.warning("[ServeLock] 无法创建锁文件 %s，跳过单实例锁", path, exc_info=True)
        return True, None

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # 被占：读一下对方的 pid 再关掉自己的 fd。读失败无所谓，纯提示用途。
        holder: int | None = None
        try:
            text = os.read(fd, 32).decode("ascii", "ignore").strip()
            holder = int(text) if text.isdigit() else None
        except OSError:
            holder = None
        os.close(fd)
        return False, holder

    # 拿到锁再写 pid：先写会导致「还没拿到锁就覆盖了对方的 pid」，让对方的错误
    # 提示指向自己。truncate 后写，避免旧内容残留成「12345  12346」这种脏读。
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        os.fsync(fd)
    except OSError:
        logger.debug("[ServeLock] 写入锁持有者 pid 失败（不影响锁本身）", exc_info=True)

    _HELD_FDS.append(fd)
    return True, None


def release() -> None:
    """释放锁（主要用于测试；正常运行中由进程退出自动释放）。"""
    while _HELD_FDS:
        fd = _HELD_FDS.pop()
        try:
            os.close(fd)
        except OSError:
            pass


def _reset_for_tests() -> None:
    """测试钩子：拆掉当前进程持有的锁 fd。"""
    release()
