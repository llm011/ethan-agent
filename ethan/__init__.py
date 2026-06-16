"""Ethan — Personal AI Agent."""
import importlib.metadata

try:
    __version__ = importlib.metadata.version("ethan-agent")
except importlib.metadata.PackageNotFoundError:
    # 源码开发环境下如果还没执行 uv sync，fallback 到这个提示
    __version__ = "unknown (install via pip or uv sync)"
