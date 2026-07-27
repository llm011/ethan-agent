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
