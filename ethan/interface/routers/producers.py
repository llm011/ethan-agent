"""Producer tasks: background generation functions that emit events into a ChatRun."""

from __future__ import annotations

import logging
import types as _types

from . import producer_browser, producer_delegate, producer_helpers, producer_native

logger = logging.getLogger(__name__)

for _module in (producer_browser, producer_delegate, producer_native, producer_helpers):
    for _name, _value in vars(_module).items():
        if not _name.startswith("__"):
            globals().setdefault(_name, _value)

# Original producers.* patch paths continue to control extracted functions.
for _module in (producer_browser, producer_delegate, producer_native, producer_helpers):
    for _name, _value in vars(_module).items():
        if isinstance(_value, _types.FunctionType) and _value.__module__ == _module.__name__:
            _bound = _types.FunctionType(_value.__code__, globals(), _value.__name__, _value.__defaults__, _value.__closure__)
            _bound.__kwdefaults__ = _value.__kwdefaults__
            _bound.__annotations__ = _value.__annotations__
            globals()[_name] = _bound
