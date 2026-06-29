"""Browser control 子系统:ethan 通过 WebSocket 驱动本机 Chrome 扩展。

链路:
    ethan agent (browser 工具)
      → BrowserHub (进程内单例) ──WebSocket──> Chrome Extension (background SW)
                                                  → CDP → Page

设计要点见 docs/browser-control-plan.md。
"""
