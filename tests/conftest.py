"""全局 pytest 配置。

autouse fixture 禁用 BGE ONNX encoder，强制走 hash embedding：
- 测试不依赖语义质量，hash embedding 足够验证接线
- 避免 ONNX Runtime 在 Linux CI 上创建非 daemon 线程池导致 pytest 进程无法退出
  （known issue: InferenceSession 的 intra-op/inter-op 线程池阻止 Python 退出）
- 与各测试文件内 hash_embed / force_hash_embed fixture 同手法，此处做全局兜底
"""
import os

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
    """绕过非 daemon 线程阻止 Python 退出的问题。

    get_session_store() 创建的单例 aiosqlite 连接（非 daemon 线程）在测试
    结束后不会被关闭，导致 pytest 跑完全部用例后进程挂起。

    用 atexit 注册 os._exit 而非直接调用：atexit 在 Python 正常关闭流程
    开始后才触发，pytest 的 terminal reporter、junitxml、coverage 等后续
    hooks 和 pytest_unconfigure 能正常执行并写完输出，再由 os._exit 强杀
    残留的非 daemon 线程。
    """
    import atexit
    atexit.register(os._exit, int(exitstatus))
