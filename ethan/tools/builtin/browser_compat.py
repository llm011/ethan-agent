"""Lazy access to the legacy browser module's dependency override surface.

The facade owns shared hooks (RPC, hub/session getters and output limits).
Resolve it only when an action runs, so importing implementations directly does
not create partial-initialization cycles and old monkeypatches still take effect.
"""
from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import browser as browser
else:
    class _BrowserFacade:
        def __getattr__(self, name: str) -> Any:
            return getattr(import_module("ethan.tools.builtin.browser"), name)

    browser = _BrowserFacade()
