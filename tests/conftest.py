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
    """关闭 get_session_store() 创建的单例 aiosqlite 连接。

    这些连接持有非 daemon worker 线程，若不显式关闭会阻止 pytest 进程退出
    （历史问题：测试跑完后进程挂起 6 小时）。

    之前用 atexit + os._exit 强杀进程，但 atexit 是 LIFO：本 hook 注册的
    os._exit 会抢先于 coverage、临时文件清理等更早注册的 atexit handler
    执行，导致这些收尾被静默跳过（coverage run 下数据丢失）。

    这里改为调用 aiosqlite Connection.stop()（同步、不依赖 event loop）：
    往 worker 线程队列投递 close+stop 哨兵，线程关闭底层 sqlite3 连接后
    正常退出。Python 走完正常关闭流程，coverage 等基于 atexit 的收尾
    也能正常跑。不能直接用 await db.close()，因为它绑定到创建时的
    event loop，测试结束后该 loop 已关闭。
    """
    try:
        from ethan.memory.session import _session_stores
    except Exception:
        return

    for store in list(_session_stores.values()):
        db = getattr(store, "_db", None)
        if db is None:
            continue
        try:
            db.stop()
        except Exception:
            pass
    _session_stores.clear()
