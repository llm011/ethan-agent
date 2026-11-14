"""全局 pytest 配置。

autouse fixture 禁用 BGE ONNX encoder，强制走 hash embedding：
- 测试不依赖语义质量，hash embedding 足够验证接线
- 避免 ONNX Runtime 在 Linux CI 上创建非 daemon 线程池导致 pytest 进程无法退出
  （known issue: InferenceSession 的 intra-op/inter-op 线程池阻止 Python 退出）
- 与各测试文件内 hash_embed / force_hash_embed fixture 同手法，此处做全局兜底
"""
import pytest


@pytest.fixture(autouse=True)
def _force_hash_embed():
    """禁用 sentence-transformers / ONNX，强制走 _hash_embed（离线、确定性）。"""
    import ethan.memory.embeddings as emb
    old_checked, old_encoder = emb._encoder_checked, emb._encoder
    emb._encoder = None
    emb._encoder_checked = True
    yield
    emb._encoder_checked, emb._encoder = old_checked, old_encoder


@pytest.fixture(autouse=True)
def _isolate_config_file(tmp_path_factory, monkeypatch):
    """把配置文件的读写指向临时目录，避免测试污染真实的 ~/.ethan/config.yaml。

    为什么需要：`save_config` 会真的写盘（并发安全改造后更明显——它还会在锁内
    重新读盘做 diff 合并）。测试里若有 `monkeypatch.setattr(cfg.providers, ...)`
    这类"改内存配置"的操作，一旦某条路径触发保存，就会把测试造出来的畸形配置
    **固化到真实文件**——实测表现为其他测试读到 `Provider 'anthropic' not found`。

    只隔离文件路径，不动配置内容：这样需要真实配置的测试（如 prompt 体积）
    仍读到用户自己的配置。
    """
    import ethan.core.config as cfg_mod

    tmp = tmp_path_factory.mktemp("config")
    cfg_file = tmp / "config.yaml"

    # 拷一份真实配置做基线（有就拷，没有就让测试自己初始化）
    real = cfg_mod.CONFIG_FILE
    if real.exists():
        try:
            cfg_file.write_text(real.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass

    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", cfg_file)
    # 清掉单例，强制重新加载临时文件
    monkeypatch.setattr(cfg_mod, "_config", None)
    yield


def pytest_sessionfinish(session, exitstatus):
    """关闭所有泄漏的 aiosqlite 连接，防止非 daemon worker 线程挂起进程。

    覆盖范围：
    - ethan.memory.session._session_stores（单例）
    - ethan.memory.api_keys._store（模块级单例）
    - ethan.interface.routers.annotations._store（模块级单例）
    - 测试里直接 SessionStore(db_path=...) 构造的非单例 store
    - 任何未来新增的 aiosqlite.connect 调用

    通过 gc 遍历所有 aiosqlite.Connection 实例，无差别 stop()。
    不用 await db.close()：连接绑定到创建时的 event loop，测试结束后
    该 loop 已关闭。stop() 是同步方法，投递 close+stop 哨兵到 worker
    线程队列，线程关闭底层 sqlite3 连接后正常退出。

    不用 atexit + os._exit：atexit LIFO 顺序会抢先于 coverage 等更早
    注册的 atexit handler，导致 coverage 数据丢失。
    """
    import gc
    try:
        import aiosqlite
    except Exception:
        return

    stopped = 0
    for obj in gc.get_objects():
        if not isinstance(obj, aiosqlite.Connection):
            continue
        # 跳过已经关闭的连接（_connection 为 None 表示底层 sqlite3 已关）
        if getattr(obj, "_connection", None) is None:
            continue
        try:
            obj.stop()
            stopped += 1
        except Exception:
            pass

    # 清空模块级单例缓存，避免后续（理论上不会有的）操作拿到已 stop 的连接
    for mod_path, attr in [
        ("ethan.memory.session", "_session_stores"),
        ("ethan.memory.api_keys", "_store"),
        ("ethan.interface.routers.annotations", "_store"),
    ]:
        try:
            mod = __import__(mod_path, fromlist=[attr])
            obj = getattr(mod, attr, None)
            if isinstance(obj, dict):
                obj.clear()
            elif obj is not None:
                # 单例对象：清掉对 _db 的引用，让 GC 回收
                setattr(mod, attr, None)
        except Exception:
            pass
