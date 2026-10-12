"""Browser 工具 —— agent 通过这四个工具操作本机 Chrome(经 BrowserHub → 扩展 → CDP)。

  browser_session : create / attach_current / list / rename / release / close
  browser_tab     : open / list / user_list / find_tab / attach / active / activate / close
  browser_page    : snapshot / click / fill / type / press / hover / select /
                    scroll / scroll_into_view / screenshot / upload / save_pdf / get / mouse / wait / eval /
                    click_selector / fill_selector / hover_selector / wait_for_element / scroll_to_text /
                    extract_content / find_elements / find_attributes / check_exist /
                    input_enter / scroll_find / click_vlm
  browser_network : start / stop / list / detail

授权(方案 Q6):会话级一次性。某 ethan 会话首次调用任意 browser 工具触发一次 consent,
批准后该会话内全部 browser 操作(含 eval)放行。consent_check 读当前会话授权态;
run() 在 consent 通过后调用,开头 mark_authorized。
"""
from __future__ import annotations

# ruff: noqa: F401
# isort: skip_file

import asyncio
import itertools
import json
import time
from pathlib import Path

from ethan.browser.auth import is_authorized, mark_authorized
from ethan.browser.hub import BrowserError, get_hub
from ethan.browser.protocol import ERROR_CODE, METHODS
from ethan.browser.session_map import get_session_map
from ethan.core.context import get_session_id
from ethan.tools.base import BaseTool


# Compatibility facade: implementations resolve shared dependencies through this
# module, so existing imports and monkeypatches keep the same behavior.
from .browser_output import (  # noqa: E402, F401
    _SNAPSHOT_DIR,
    _SNAPSHOT_CHUNK_CHARS,
    _SNAPSHOT_NEWLINE_SEARCH_RADIUS,
    _PERSIST_SEQ,
    _persist_snapshot,
    _EVAL_MAX_CHARS,
    _USER_TABS_MAX_CHARS,
    _USER_TABS_DIR,
    _pack_user_tabs,
    _truncate_eval_result,
    _chunk_text,
)
from .browser_selectors import (  # noqa: E402, F401
    _MARKDOWN_SCRIPT,
    _eval_js,
    _click_point,
    _build_locate_script,
)
from .browser_runtime import (  # noqa: E402, F401
    _STEP_ACTIONS,
    _HINTS,
    _call,
    _require_owned_or_recover,
    _require_owned,
    _extract_session_id,
    _annotate_sessions,
    _ACTIVE_TAB_TTL,
    _active_tab_cache,
    _describe_clients,
    _clients_hint,
    _list_sessions_all_clients,
    _consent_desc,
    _BrowserToolBase,
)
from .browser_sessions import (  # noqa: E402, F401
    BrowserSessionTool,
    BrowserClientTool,
)
from .browser_tabs import (  # noqa: E402, F401
    BrowserTabTool,
)
from .browser_page import (  # noqa: E402, F401
    BrowserPageTool,
)
from .browser_network import (  # noqa: E402, F401
    BrowserNetworkTool,
)
