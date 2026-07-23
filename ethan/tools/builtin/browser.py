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

import asyncio
import json
import time
from pathlib import Path

from ethan.browser.auth import is_authorized, mark_authorized
from ethan.browser.hub import BrowserError, get_hub
from ethan.browser.protocol import ERROR_CODE, METHODS
from ethan.browser.session_map import get_session_map
from ethan.core.context import get_session_id
from ethan.tools.base import BaseTool

# snapshot 分页：完整内容落盘 /tmp，prompt 里只带首段，agent 按需翻页读取。
_SNAPSHOT_DIR = Path("/tmp/ethan-snapshots")
_SNAPSHOT_CHUNK_CHARS = 10000  # 每段目标字符数，在换行符处对齐截断
_SNAPSHOT_NEWLINE_SEARCH_RADIUS = 500  # 截断点附近向前搜索换行符的范围


def _persist_snapshot(content: str, session: str) -> str:
    """完整 snapshot 文本落盘，返回文件路径。"""
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe = (session or "unknown").replace("/", "_").replace("\\", "_")
    path = _SNAPSHOT_DIR / f"{safe}-{int(time.time() * 1000)}.txt"
    path.write_text(content, encoding="utf-8")
    return str(path)


def _chunk_text(content: str, offset: int, length: int) -> tuple[str, int]:
    """从 offset 取 length 字符，在末尾附近找换行符对齐截断。

    找不到换行符（前后 _SNAPSHOT_NEWLINE_SEARCH_RADIUS 字符内都没有）就硬截断。
    返回 (chunk, actual_length)。
    """
    total = len(content)
    if offset >= total:
        return "", 0
    end = min(offset + length, total)
    if end < total:
        search_start = max(offset, end - _SNAPSHOT_NEWLINE_SEARCH_RADIUS)
        search_end = min(total, end + _SNAPSHOT_NEWLINE_SEARCH_RADIUS)
        newline_pos = content.rfind("\n", search_start, search_end)
        if newline_pos > offset:
            end = newline_pos + 1
    chunk = content[offset:end]
    return chunk, end - offset


# ── selector 操作辅助函数（Python 侧组合现有 CDP 方法，不改扩展）──


async def _eval_js(session: str, script: str):
    """执行页面 JS，返回解析后的 value。"""
    result = await _call("page_eval", {"sessionId": session, "script": script},
                         browser_session_id=session)
    if isinstance(result, dict):
        return result.get("value")
    return result


async def _click_point(session: str, x: float, y: float):
    """在指定坐标模拟真实鼠标点击（move + down + up），绕过 eval .click() 的 React 问题。"""
    await _call("page_mouse", {"sessionId": session, "action": "move", "x": x, "y": y},
                browser_session_id=session)
    await _call("page_mouse", {"sessionId": session, "action": "down", "button": "left"},
                browser_session_id=session)
    await _call("page_mouse", {"sessionId": session, "action": "up", "button": "left"},
                browser_session_id=session)


def _build_locate_script(selector: str = "", xpath: str = "", text: str = "", nth: int = 0) -> str:
    """生成定位元素的 JS，返回 {x, y, text, found} 或 {found: false}。"""
    import json as _json
    if selector:
        return f"""(() => {{
  const el = document.querySelector({_json.dumps(selector)});
  if (!el) return JSON.stringify({{found: false}});
  el.scrollIntoView({{block: 'center'}});
  const r = el.getBoundingClientRect();
  return JSON.stringify({{found: true, x: r.x + r.width/2, y: r.y + r.height/2, text: (el.innerText||'').slice(0, 80)}});
}})()"""
    if xpath:
        return f"""(() => {{
  const el = document.evaluate({_json.dumps(xpath)}, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  if (!el) return JSON.stringify({{found: false}});
  el.scrollIntoView({{block: 'center'}});
  const r = el.getBoundingClientRect();
  return JSON.stringify({{found: true, x: r.x + r.width/2, y: r.y + r.height/2, text: (el.innerText||'').slice(0, 80)}});
}})()"""
    if text:
        return f"""(() => {{
  const els = [...document.querySelectorAll('*')].filter(el => {{
    const t = el.innerText || '';
    return t.includes({_json.dumps(text)}) && el.children.length <= 5 && el.offsetParent !== null;
  }});
  const el = els[{nth}] || els[0];
  if (!el) return JSON.stringify({{found: false, match_count: els.length}});
  el.scrollIntoView({{block: 'center'}});
  const r = el.getBoundingClientRect();
  return JSON.stringify({{found: true, x: r.x + r.width/2, y: r.y + r.height/2, text: (el.innerText||'').slice(0, 80), match_count: els.length}});
}})()"""
    return "JSON.stringify({found: false, error: '需要 selector/xpath/text 之一'})"


# 计步动作（交互/变更类）；snapshot/get/wait/screenshot 不计步
_STEP_ACTIONS = frozenset({
    "click", "fill", "type", "press", "hover", "select",
    "scroll", "scroll_into_view", "mouse", "eval",
    "click_selector", "fill_selector", "hover_selector", "scroll_to_text",
    "input_enter", "scroll_find", "click_vlm",
})

# 每个 action 返回值的字段说明，注入到 JSON 的 _hint 字段，帮模型理解输出结构和下一步用法
_HINTS = {
    "snapshot": (
        "页面无障碍树。节点格式形如 [ref] \"名称\" role，ref 用于后续 "
        "click/fill/type/hover/select/scroll_into_view/get/upload。"
        "ref 仅对本次 snapshot 有效，页面跳转/刷新后需重新 snapshot。"
        "完整 snapshot 已落盘到 snapshot_path；has_more=true 时当前只是首段，"
        "用 snapshot_read(action=snapshot_read, path=snapshot_path, offset=chunk_length) 读取后续段落。"
    ),
    "snapshot_read": (
        "读取已落盘 snapshot 文件的指定段落。snapshot 字段是本段 AX 树文本；"
        "has_more=true 表示还有后续内容，用 offset+chunk_length 作为下次的 offset 继续读取。"
        "找到目标 ref 后，回到 browser_page 用 click/fill 等操作（ref 仍然有效）。"
    ),
    "get": "读取 what 指定的内容。value 字段是读取结果；page.url/page.title 是当前页信息。",
    "click": "点击已执行。ok=true 表示成功，ref 在页面未跳转/刷新前可继续使用。",
    "fill": "已清空输入框并填入文本。ok=true 表示成功。",
    "type": "已在元素上逐字输入。ok=true 表示成功。",
    "press": "已按下按键。ok=true 表示成功。",
    "hover": "已悬停。ok=true 表示成功。",
    "select": "已选择选项。ok=true 表示成功。",
    "scroll_into_view": "已将元素滚入视口。ok=true 表示成功。",
    "scroll": "已滚动页面。ok=true 表示成功。",
    "mouse": "已执行坐标级鼠标事件。ok=true 表示成功。",
    "wait": "已等待指定时长或加载状态。",
    "screenshot": "已截图并保存。path 是本地图片路径，前端会自动渲染。",
    "upload": "已上传文件。ok=true 表示成功。",
    "save_pdf": "已保存 PDF。path 是文件路径。",
    "eval": "已执行页面 JS。value 字段是脚本返回值（若有）。",
    "click_selector": "用 CSS/XPath/text 定位元素并点击。ok=true 表示成功，coords 是点击坐标。不依赖 snapshot ref。",
    "fill_selector": "用 CSS/XPath 定位输入框并填入文本（兼容 React）。ok=true 表示成功。",
    "hover_selector": "用 CSS/XPath/text 定位元素并悬停。ok=true 表示成功。",
    "wait_for_element": "轮询等待元素出现。found=true 表示已出现，false 表示超时未找到。",
    "scroll_to_text": "按文本搜索并滚动到该位置。found=true 表示已找到并滚动到位。",
    "extract_content": "提取元素 innerText。text 是内容，length 是总长度。truncated=true 表示已截断。",
    "find_elements": "返回匹配 selector 的元素列表。count 是总数，elements 含每个元素的 tag/text/坐标（最多 50 个）。",
    "find_attributes": "返回元素属性值。attributes 是 {属性名: 值} 字典。",
    "check_exist": "检查元素是否存在。exist=true/false。",
    "input_enter": "在输入框填入文本并回车（组合动作）。ok=true 表示成功。",
    "scroll_find": "边滚动边查找元素。found=true 表示已找到，scrolls 是滚动次数。",
    "click_vlm": "VLM 视觉点击。截图发给多模态 LLM 识别坐标后用 CDP mouse 点击。ok=true 表示成功，screenshot 是截图路径。",
}


async def _call(method_key: str, params: dict, browser_session_id: str | None = None):
    # 会话隔离门禁:凡是操作既有 browser session 的调用,该 session 必须属于当前 ethan 会话。
    # create/attach_current 不传 browser_session_id(新建后才 bind),session_list/user_list 同理,
    # 所以这一处收口即可覆盖 rename/release/close + 全部 tab/page 操作,杜绝跨会话/跨用户操控。
    if browser_session_id is not None:
        _require_owned(browser_session_id)
    hub = get_hub()
    result = await hub.call(METHODS[method_key], params, browser_session_id=browser_session_id)
    if browser_session_id:
        get_session_map().touch(browser_session_id)
    return result


def _require_owned(browser_session_id: str) -> None:
    """校验 browser session 归属当前 ethan 会话,不属于则拒绝。"""
    owned = get_session_map().list_for(get_session_id())
    if not browser_session_id or browser_session_id not in owned:
        raise BrowserError(
            "该 browser session 不属于当前对话,拒绝操作",
            code=ERROR_CODE["session_not_found"],
        )


def _extract_session_id(result: dict | None) -> str | None:
    """从 create/attach_current 结果里取 browser session id。

    扩展返回 {created/attached: true, session: {sessionId: ...}};兼容顶层平铺写法。
    """
    if not result:
        return None
    sess = result.get("session")
    if isinstance(sess, dict):
        sid = sess.get("sessionId") or sess.get("session_id")
        if sid:
            return sid
    return result.get("session_id") or result.get("sessionId")


def _filter_owned_sessions(result: dict | None) -> dict:
    """session_list 结果按当前 ethan 会话过滤,避免泄漏其他会话/用户的 session。"""
    result = result or {}
    owned = set(get_session_map().list_for(get_session_id()))
    sessions = result.get("sessions")
    if isinstance(sessions, list):
        kept = [s for s in sessions if isinstance(s, dict)
                and (s.get("sessionId") or s.get("session_id")) in owned]
        return {**result, "sessions": kept}
    return result


def _consent_desc() -> str | None:
    """会话级门禁:已授权返回 None(放行),否则返回授权说明触发 consent。"""
    if is_authorized(get_session_id()):
        return None
    return "操作本机浏览器(创建/控制页面、点击输入、执行页面脚本)"


class _BrowserToolBase(BaseTool):
    fast_path: bool = False
    cacheable = False  # 浏览器操作有副作用,不缓存
    side_effect = True
    # 浏览器工具输出是带 ID/ref 的结构化 JSON(tab_id、session_id、snapshot ref),
    # 压缩会把这些 ID 揉成散文摘要 → 模型拿不到 ID 就无法 close/activate/click,
    # 表现为「列出来了却不知道怎么操作」。必须逐字给模型,绝不压成摘要。
    no_compress = True

    def consent_check(self, **kwargs) -> str | None:
        return _consent_desc()

    def _authorize(self) -> None:
        mark_authorized(get_session_id())


class BrowserSessionTool(_BrowserToolBase):
    name = "browser_session"
    description = (
        "管理浏览器 session(一个 session 对应一个 Chrome Tab Group)。"
        "action=create 新建并打开 url;attach_current 接管当前 active tab;"
        "list 列出 session;rename 改名;update 更新标题和颜色;release 放掉控制权但保留 tab;close 关闭整个 tab group。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "attach_current", "list", "rename", "release", "close", "update"]},
            "session": {"type": "string", "description": "目标 session_id(rename/release/close 必填)"},
            "url": {"type": "string", "description": "create 时打开的初始 URL"},
            "title": {"type": "string", "description": "session 标题(create/attach_current/rename)"},
            "color": {"type": "string", "description": "Tab Group 颜色（grey/blue/red/yellow/green/pink/purple/cyan/orange）"},
            "keep_alive": {"type": "boolean", "description": "create/attach_current 时标记此 session 在对话结束后保留（不自动关闭 tab group）。默认 false（用完即关）。用户只是让帮个忙、页面还要继续看时设 true。"},
        },
        "required": ["action"],
    }

    async def run(self, action: str, session: str = "", url: str = "", title: str = "", color: str = "", keep_alive: bool = False) -> str:
        self._authorize()
        try:
            if action == "create":
                params: dict = {}
                if url:
                    params["url"] = url
                if title:
                    params["title"] = title
                if color:
                    params["color"] = color
                result = await _call("session_create", params)
                bsid = _extract_session_id(result)
                if bsid:
                    get_session_map().bind(bsid, get_session_id(), keep_alive=keep_alive)
                return json.dumps(result, ensure_ascii=False)
            if action == "attach_current":
                params = {}
                if title:
                    params["title"] = title
                if color:
                    params["color"] = color
                result = await _call("session_attach_current", params)
                bsid = _extract_session_id(result)
                if bsid:
                    get_session_map().bind(bsid, get_session_id(), keep_alive=keep_alive)
                return json.dumps(result, ensure_ascii=False)
            if action == "list":
                result = await _call("session_list", {})
                return json.dumps(_filter_owned_sessions(result), ensure_ascii=False)
            if action == "rename":
                return json.dumps(await _call("session_rename", {"sessionId": session, "title": title},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "release":
                out = await _call("session_release", {"sessionId": session}, browser_session_id=session)
                get_session_map().unbind(session)
                return json.dumps(out, ensure_ascii=False)
            if action == "close":
                out = await _call("session_close", {"sessionId": session}, browser_session_id=session)
                get_session_map().unbind(session)
                return json.dumps(out, ensure_ascii=False)
            if action == "update":
                params = {"sessionId": session}
                if title:
                    params["title"] = title
                if color:
                    params["color"] = color
                return json.dumps(await _call("session_update", params,
                                              browser_session_id=session), ensure_ascii=False)
            return f"未知 action: {action}"
        except BrowserError as e:
            return f"浏览器错误: {e}" + (" (可重新 snapshot 后重试)" if e.retryable else "")


class BrowserTabTool(_BrowserToolBase):
    name = "browser_tab"
    description = (
        "管理 session 内的 tab。open 新开 tab;list 列出 session 内 tab;"
        "user_list 列出用户所有 tab;find_tab 按 URL/域名查找已开 tab(active_only=true 取用户当前活动 tab);"
        "attach 把已有 tab 纳入 session;attach_batch 批量把多个 tab 纳入 session;"
        "active 取当前活动 tab;activate 切换活动 tab;close 关闭 tab;"
        "detach 把 tab 移出 session(取消分组但不关闭);move 调整 tab 在组内的位置。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["open", "list", "user_list", "find_tab", "attach", "attach_batch", "active", "activate", "close", "detach", "move"]},
            "session": {"type": "string", "description": "目标 session_id"},
            "tab": {"type": "string", "description": "目标 tab_id(attach/activate/close)"},
            "url": {"type": "string", "description": "open 时打开的 URL;find_tab 时按域名或 URL 前缀匹配"},
            "active_only": {"type": "boolean", "description": "find_tab 专用:true=只返回用户当前活动的 tab,忽略 url"},
            "tabs": {"type": "array", "items": {"type": "string"}, "description": "attach_batch 时的 tab_id 列表"},
            "index": {"type": "integer", "description": "move 时的目标位置索引"},
        },
        "required": ["action"],
    }

    async def run(self, action: str, session: str = "", tab: str = "", url: str = "", active_only: bool = False, tabs: list = None, index: int = -1) -> str:
        self._authorize()
        try:
            if action == "open":
                return json.dumps(await _call("tab_open", {"sessionId": session, "url": url},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "list":
                return json.dumps(await _call("tab_list", {"sessionId": session},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "user_list":
                return json.dumps(await _call("tab_user_list", {}), ensure_ascii=False)
            if action == "find_tab":
                result = await _call("tab_user_list", {})
                tabs = result.get("tabs", []) if isinstance(result, dict) else []
                if active_only:
                    matched = [t for t in tabs if t.get("active")]
                elif url:
                    from urllib.parse import urlparse
                    try:
                        target = urlparse(url).netloc or url
                    except Exception:
                        target = url
                    matched = [t for t in tabs if target in (t.get("url") or "")]
                else:
                    matched = tabs
                if not matched:
                    return json.dumps({"found": False, "tab": None}, ensure_ascii=False)
                return json.dumps({"found": True, "tab": matched[0]}, ensure_ascii=False)
            if action == "attach":
                return json.dumps(await _call("tab_attach", {"sessionId": session, "tabId": tab},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "attach_batch":
                tab_ids = tabs or []
                return json.dumps(await _call("tab_attach_batch", {"sessionId": session, "tabIds": tab_ids},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "active":
                return json.dumps(await _call("tab_active", {"sessionId": session},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "activate":
                return json.dumps(await _call("tab_activate", {"sessionId": session, "tabId": tab},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "close":
                return json.dumps(await _call("tab_close", {"sessionId": session, "tabId": tab},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "detach":
                return json.dumps(await _call("tab_detach", {"sessionId": session, "tabId": tab},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "move":
                return json.dumps(await _call("tab_move", {"sessionId": session, "tabId": tab, "index": index},
                                              browser_session_id=session), ensure_ascii=False)
            return f"未知 action: {action}"
        except BrowserError as e:
            return f"浏览器错误: {e}" + (" (可重新 snapshot 后重试)" if e.retryable else "")


class BrowserPageTool(_BrowserToolBase):
    name = "browser_page"
    description = (
        "操作 session 的 active tab。snapshot 取页面 AX 树+ref(默认 interactive+compact),"
        "完整内容落盘/tmp,prompt 只带首段 10000 字,has_more=true 时用 snapshot_read 翻页;"
        "click/fill/type/press/hover/select/scroll_into_view 用 ref 交互;"
        "click_selector/fill_selector/hover_selector 用 CSS/XPath/text 直接定位(不依赖 snapshot,CDP mouse 真实点击);"
        "wait_for_element 等元素出现;scroll_to_text 按文本滚动;extract_content 提取内容;"
        "find_elements/find_attributes/check_exist 查询元素;"
        "input_enter 输入+回车;scroll_find 滚动查找;"
        "click_vlm 截图发给多模态 LLM 识别后点击(AX 树失效时的终极 fallback);"
        "scroll 滚动;mouse 发坐标级鼠标事件;get 读 title/url/text/value/html/box;"
        "screenshot 截图;upload 上传文件;wait 等待;eval 执行页面 JS(高权限)。"
        "ref 仅对最近一次 snapshot 可靠,页面跳转/刷新后需重新 snapshot。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [
                "snapshot", "snapshot_read", "click", "fill", "type", "press", "hover", "select",
                "scroll", "scroll_into_view", "screenshot", "upload", "save_pdf", "get", "mouse", "wait", "eval",
                "click_selector", "fill_selector", "hover_selector", "wait_for_element", "scroll_to_text",
                "extract_content", "find_elements", "find_attributes", "check_exist",
                "input_enter", "scroll_find", "click_vlm",
            ]},
            "session": {"type": "string", "description": "目标 session_id(snapshot_read 不需要)"},
            "ref": {"type": "string", "description": "snapshot 返回的元素 ref(click/fill/type/hover/select/get/scroll_into_view/upload)"},
            "text": {"type": "string", "description": "fill/type/scroll_to_text/input_enter 的文本"},
            "key": {"type": "string", "description": "press 的按键,如 Enter"},
            "value": {"type": "string", "description": "select 的选项值"},
            "files": {"type": "array", "items": {"type": "string"}, "description": "upload 时的本地文件路径列表"},
            "pdf_path": {"type": "string", "description": "save_pdf 输出路径(可选,不填自动生成)"},
            "pdf_format": {"type": "string", "enum": ["a4", "letter", "legal", "a3", "tabloid"], "description": "save_pdf 纸张规格,默认 a4"},
            "landscape": {"type": "boolean", "description": "save_pdf 横向纸张"},
            "what": {"type": "string", "enum": ["title", "url", "text", "value", "html", "box"], "description": "get 读取的内容"},
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "description": "scroll 方向"},
            "pixels": {"type": "integer", "description": "scroll 像素"},
            "mouse_action": {"type": "string", "enum": ["move", "down", "up", "wheel"], "description": "mouse 子动作"},
            "x": {"type": "number"}, "y": {"type": "number"},
            "delta_x": {"type": "number"}, "delta_y": {"type": "number"},
            "ms": {"type": "integer", "description": "wait 毫秒"},
            "load": {"type": "string", "description": "wait 的加载状态,如 domcontentloaded"},
            "script": {"type": "string", "description": "eval 执行的 JS"},
            # snapshot 选项(默认交给模型,见方案 Q7)
            "interactive": {"type": "boolean", "description": "snapshot 只看交互元素(推荐默认 true)"},
            "compact": {"type": "boolean", "description": "snapshot 压缩空结构节点(推荐默认 true)"},
            "depth": {"type": "integer", "description": "snapshot 树深度上限"},
            "selector": {"type": "string", "description": "CSS 选择器(snapshot 限定 DOM 子树 / click_selector/fill_selector/hover_selector/wait_for_element/find_elements/find_attributes/check_exist/scroll_find 定位元素)"},
            "cursor": {"type": "boolean", "description": "snapshot 补充 cursor:pointer/onclick 元素"},
            "urls": {"type": "boolean", "description": "snapshot 包含链接 href"},
            "format": {"type": "string", "enum": ["text", "json"], "description": "snapshot 输出格式"},
            # snapshot_read 选项
            "path": {"type": "string", "description": "snapshot_read 读取的文件路径(snapshot 返回的 snapshot_path)"},
            "offset": {"type": "integer", "description": "snapshot_read 读取的字符偏移,默认 0"},
            "length": {"type": "integer", "description": "snapshot_read 读取的长度,默认 10000"},
            # selector 操作选项
            "xpath": {"type": "string", "description": "XPath 表达式(click_selector/fill_selector/hover_selector 定位元素)"},
            "nth": {"type": "integer", "description": "按 text 定位时取第几个匹配(从 0 开始,默认 0)"},
            "timeout": {"type": "integer", "description": "wait_for_element 超时毫秒,默认 10000"},
            "strip_links": {"type": "boolean", "description": "extract_content 是否去除链接信息"},
            "attributes": {"type": "array", "items": {"type": "string"}, "description": "find_attributes 要提取的属性名列表"},
            "scroll_times": {"type": "integer", "description": "scroll_find 最大滚动次数,默认 3"},
            "prompt": {"type": "string", "description": "click_vlm 的目标元素描述,如'字节范 M+ 按钮'"},
        },
        "required": ["action"],
    }

    async def run(self, action: str, session: str = "", **kw) -> str:
        self._authorize()
        try:
            raw = await self._run_impl(action, session, **kw)
        except BrowserError as e:
            return f"浏览器错误: {e}" + (" (可重新 snapshot 后重试)" if e.retryable else "")
        return self._enrich(raw, action, session)

    async def _run_impl(self, action: str, session: str = "", **kw) -> str:
        if action == "snapshot":
            params = {"sessionId": session}
            for k in ("interactive", "compact", "depth", "selector", "cursor", "urls", "format"):
                if kw.get(k) is not None:
                    params[k] = kw[k]
            result = await _call("page_snapshot", params, browser_session_id=session)
            if not isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False)
            # 完整 snapshot 文本落盘，prompt 只带首段
            full_snapshot = result.get("snapshot", "")
            snap_path = _persist_snapshot(full_snapshot, session)
            total = len(full_snapshot)
            chunk, chunk_len = _chunk_text(full_snapshot, 0, _SNAPSHOT_CHUNK_CHARS)
            has_more = chunk_len < total
            out = dict(result)
            out["snapshot"] = chunk
            out["snapshot_path"] = snap_path
            out["total_chars"] = total
            out["chunk_offset"] = 0
            out["chunk_length"] = chunk_len
            out["has_more"] = has_more
            return json.dumps(out, ensure_ascii=False)
        if action == "snapshot_read":
            path = kw.get("path", "")
            if not path:
                return json.dumps({"error": "snapshot_read 需要 path 参数（snapshot 返回的 snapshot_path）"},
                                  ensure_ascii=False)
            offset = int(kw.get("offset", 0))
            length = int(kw.get("length", _SNAPSHOT_CHUNK_CHARS))
            try:
                content = Path(path).read_text(encoding="utf-8")
            except (OSError, FileNotFoundError) as e:
                return json.dumps({"error": f"读取 snapshot 文件失败: {e}"}, ensure_ascii=False)
            total = len(content)
            chunk, chunk_len = _chunk_text(content, offset, length)
            has_more = offset + chunk_len < total
            return json.dumps({
                "path": path,
                "total_chars": total,
                "offset": offset,
                "chunk_length": chunk_len,
                "has_more": has_more,
                "snapshot": chunk,
            }, ensure_ascii=False)
        if action == "click":
            return json.dumps(await _call("page_click", {"sessionId": session, "ref": kw.get("ref")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "fill":
            return json.dumps(await _call("page_fill", {"sessionId": session, "ref": kw.get("ref"), "text": kw.get("text", "")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "type":
            return json.dumps(await _call("page_type", {"sessionId": session, "ref": kw.get("ref"), "text": kw.get("text", "")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "press":
            return json.dumps(await _call("page_press", {"sessionId": session, "key": kw.get("key")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "hover":
            return json.dumps(await _call("page_hover", {"sessionId": session, "ref": kw.get("ref")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "select":
            return json.dumps(await _call("page_select", {"sessionId": session, "ref": kw.get("ref"), "value": kw.get("value")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "scroll_into_view":
            return json.dumps(await _call("page_scroll_into_view", {"sessionId": session, "ref": kw.get("ref")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "scroll":
            params = {"sessionId": session, "direction": kw.get("direction", "down")}
            if kw.get("pixels") is not None:
                params["pixels"] = kw["pixels"]
            return json.dumps(await _call("page_scroll", params, browser_session_id=session), ensure_ascii=False)
        if action == "get":
            params = {"sessionId": session, "what": kw.get("what")}
            if kw.get("ref"):
                params["ref"] = kw["ref"]
            return json.dumps(await _call("page_get", params, browser_session_id=session), ensure_ascii=False)
        if action == "mouse":
            params = {"sessionId": session, "action": kw.get("mouse_action", "move")}
            for k in ("x", "y", "delta_x", "delta_y"):
                if kw.get(k) is not None:
                    params[{"delta_x": "deltaX", "delta_y": "deltaY"}.get(k, k)] = kw[k]
            return json.dumps(await _call("page_mouse", params, browser_session_id=session), ensure_ascii=False)
        if action == "wait":
            params = {"sessionId": session}
            if kw.get("ms") is not None:
                params["ms"] = kw["ms"]
            if kw.get("load"):
                params["load"] = kw["load"]
            return json.dumps(await _call("page_wait", params, browser_session_id=session), ensure_ascii=False)
        if action == "screenshot":
            from ethan.browser.screenshot import save_screenshot
            result = await _call("page_screenshot", {"sessionId": session}, browser_session_id=session)
            return await save_screenshot(result)
        if action == "upload":
            return json.dumps(await _call(
                "page_upload",
                {"sessionId": session, "ref": kw.get("ref"), "files": kw.get("files", [])},
                browser_session_id=session,
            ), ensure_ascii=False)
        if action == "save_pdf":
            import time as _time

            from ethan.browser.screenshot import shots_dir
            params: dict = {"sessionId": session}
            if kw.get("pdf_format"):
                params["paperFormat"] = kw["pdf_format"]
            if kw.get("landscape") is not None:
                params["landscape"] = kw["landscape"]
            out_path = kw.get("pdf_path")
            if not out_path:
                d = shots_dir().parent / "browser-pdfs"
                d.mkdir(parents=True, exist_ok=True)
                out_path = str(d / f"page-{int(_time.time() * 1000)}.pdf")
            params["path"] = out_path
            result = await _call("page_save_pdf", params, browser_session_id=session)
            return json.dumps({**(result or {}), "path": out_path}, ensure_ascii=False)
        if action == "eval":
            return json.dumps(await _call("page_eval", {"sessionId": session, "script": kw.get("script", "")},
                                          browser_session_id=session), ensure_ascii=False)
        # ── selector 操作（不依赖 snapshot，直接用 CSS/XPath/text 定位 + CDP mouse 点击）──
        if action == "click_selector":
            script = _build_locate_script(kw.get("selector", ""), kw.get("xpath", ""),
                                          kw.get("text", ""), int(kw.get("nth", 0)))
            raw = await _eval_js(session, script)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not info.get("found"):
                return json.dumps({"ok": False, "error": "未找到匹配元素",
                                   "match_count": info.get("match_count", 0)}, ensure_ascii=False)
            await _click_point(session, info["x"], info["y"])
            return json.dumps({"ok": True, "method": "selector/xpath/text",
                               "coords": {"x": info["x"], "y": info["y"]},
                               "text": info.get("text", "")}, ensure_ascii=False)
        if action == "fill_selector":
            import json as _json
            sel = kw.get("selector", "")
            xp = kw.get("xpath", "")
            txt = kw.get("text", "")
            locate = _build_locate_script(sel, xp, "", 0)
            raw = await _eval_js(session, locate)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not info.get("found"):
                return json.dumps({"ok": False, "error": "未找到匹配输入框"}, ensure_ascii=False)
            # 聚焦 + 清空 + 设值 + 触发 input/change 事件（兼容 React）
            fill_script = f"""(() => {{
  const el = document.querySelector({_json.dumps(sel)}) ||
    document.evaluate({_json.dumps(xp)}, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  if (!el) return false;
  el.focus();
  el.value = {_json.dumps(txt)};
  el.dispatchEvent(new Event('input', {{bubbles: true}}));
  el.dispatchEvent(new Event('change', {{bubbles: true}}));
  return true;
}})()"""
            if not sel and not xp:
                # fallback：用坐标 click 后用 page_fill（需要 ref，这里用 eval 设值）
                await _click_point(session, info["x"], info["y"])
                fill_script = f"""(() => {{
  const el = document.activeElement;
  if (!el) return false;
  el.value = {_json.dumps(txt)};
  el.dispatchEvent(new Event('input', {{bubbles: true}}));
  el.dispatchEvent(new Event('change', {{bubbles: true}}));
  return true;
}})()"""
            await _eval_js(session, fill_script)
            return json.dumps({"ok": True, "text": txt}, ensure_ascii=False)
        if action == "hover_selector":
            script = _build_locate_script(kw.get("selector", ""), kw.get("xpath", ""),
                                          kw.get("text", ""), int(kw.get("nth", 0)))
            raw = await _eval_js(session, script)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not info.get("found"):
                return json.dumps({"ok": False, "error": "未找到匹配元素"}, ensure_ascii=False)
            await _call("page_mouse", {"sessionId": session, "action": "move",
                                       "x": info["x"], "y": info["y"]}, browser_session_id=session)
            return json.dumps({"ok": True, "coords": {"x": info["x"], "y": info["y"]}},
                              ensure_ascii=False)
        if action == "wait_for_element":
            import json as _json
            sel = kw.get("selector", "")
            timeout = int(kw.get("timeout", 10000))
            check_script = f"!!document.querySelector({_json.dumps(sel)})"
            deadline = asyncio.get_event_loop().time() + timeout / 1000
            while asyncio.get_event_loop().time() < deadline:
                raw = await _eval_js(session, check_script)
                if raw is True or raw == "true":
                    return json.dumps({"ok": True, "found": True, "selector": sel},
                                      ensure_ascii=False)
                await asyncio.sleep(0.3)
            return json.dumps({"ok": False, "found": False, "selector": sel,
                               "timeout_ms": timeout}, ensure_ascii=False)
        if action == "scroll_to_text":
            import json as _json
            txt = kw.get("text", "")
            script = f"""(() => {{
  const found = window.find({_json.dumps(txt)}, false, false, true, false, false, false);
  if (!found) return JSON.stringify({{found: false}});
  const sel = window.getSelection();
  if (sel.rangeCount > 0) {{
    const range = sel.getRangeAt(0);
    range.startContainer.parentElement?.scrollIntoView({{block: 'center'}});
    const r = range.getBoundingClientRect();
    return JSON.stringify({{found: true, x: r.x + r.width/2, y: r.y + r.height/2}});
  }}
  return JSON.stringify({{found: false}});
}})()"""
            raw = await _eval_js(session, script)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            return json.dumps(info, ensure_ascii=False)
        if action == "extract_content":
            import json as _json
            sel = kw.get("selector", "body")
            strip_links = kw.get("strip_links", False)
            script = f"""(() => {{
  const el = document.querySelector({_json.dumps(sel)}) || document.body;
  let text = el.innerText || '';
  {_json.dumps(strip_links) if strip_links else 'false'} && el.querySelectorAll('a').forEach(a => {{
    // keep text, strip href
  }});
  return JSON.stringify({{text: text, length: text.length, selector: {_json.dumps(sel)}}});
}})()"""
            raw = await _eval_js(session, script)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            # 内容太长时截断并提示
            max_len = 20000
            if info.get("length", 0) > max_len:
                info["truncated"] = True
                info["text"] = info["text"][:max_len]
                info["_hint"] = f"内容已截断（共 {info['length']} 字，前 {max_len} 字）。"
            return json.dumps(info, ensure_ascii=False)
        if action == "find_elements":
            import json as _json
            sel = kw.get("selector", "")
            script = f"""(() => {{
  const els = document.querySelectorAll({_json.dumps(sel)});
  const results = [];
  for (let i = 0; i < Math.min(els.length, 50); i++) {{
    const r = els[i].getBoundingClientRect();
    results.push({{
      index: i,
      tag: els[i].tagName.toLowerCase(),
      text: (els[i].innerText || '').slice(0, 60),
      x: Math.round(r.x + r.width/2),
      y: Math.round(r.y + r.height/2),
    }});
  }}
  return JSON.stringify({{count: els.length, elements: results}});
}})()"""
            raw = await _eval_js(session, script)
            return raw if isinstance(raw, str) else json.dumps(raw or {}, ensure_ascii=False)
        if action == "find_attributes":
            import json as _json
            sel = kw.get("selector", "")
            attrs = kw.get("attributes", [])
            attrs_js = _json.dumps(attrs)
            script = f"""(() => {{
  const el = document.querySelector({_json.dumps(sel)});
  if (!el) return JSON.stringify({{found: false}});
  const attrs = {attrs_js};
  const result = {{}};
  attrs.forEach(a => {{ result[a] = el.getAttribute(a); }});
  return JSON.stringify({{found: true, attributes: result}});
}})()"""
            raw = await _eval_js(session, script)
            return raw if isinstance(raw, str) else json.dumps(raw or {}, ensure_ascii=False)
        if action == "check_exist":
            import json as _json
            sel = kw.get("selector", "")
            script = f"JSON.stringify({{exist: !!document.querySelector({_json.dumps(sel)})}})"
            raw = await _eval_js(session, script)
            return raw if isinstance(raw, str) else json.dumps(raw or {}, ensure_ascii=False)
        if action == "input_enter":
            import json as _json
            sel = kw.get("selector", "")
            txt = kw.get("text", "")
            fill_script = f"""(() => {{
  const el = document.querySelector({_json.dumps(sel)});
  if (!el) return false;
  el.focus();
  el.value = {_json.dumps(txt)};
  el.dispatchEvent(new Event('input', {{bubbles: true}}));
  el.dispatchEvent(new Event('change', {{bubbles: true}}));
  el.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}}));
  return true;
}})()"""
            await _eval_js(session, fill_script)
            # 也用 CDP press Enter 确保触发
            await _call("page_press", {"sessionId": session, "key": "Enter"},
                        browser_session_id=session)
            return json.dumps({"ok": True, "text": txt, "selector": sel},
                              ensure_ascii=False)
        if action == "scroll_find":
            import json as _json
            sel = kw.get("selector", "")
            scroll_times = int(kw.get("scroll_times", 3))
            for i in range(scroll_times):
                check = f"JSON.stringify({{found: !!document.querySelector({_json.dumps(sel)}), count: document.querySelectorAll({_json.dumps(sel)}).length}})"
                raw = await _eval_js(session, check)
                info = json.loads(raw) if isinstance(raw, str) else (raw or {})
                if info.get("found"):
                    return json.dumps({"ok": True, "found": True, "count": info.get("count", 1),
                                       "scrolls": i, "selector": sel}, ensure_ascii=False)
                await _call("page_scroll", {"sessionId": session, "direction": "down", "pixels": 500},
                            browser_session_id=session)
                await asyncio.sleep(0.5)
            return json.dumps({"ok": False, "found": False, "scrolls": scroll_times,
                               "selector": sel}, ensure_ascii=False)
        if action == "click_vlm":
            return await self._vlm_click(kw.get("prompt", ""), session)
        return f"未知 action: {action}"

    async def _vlm_click(self, prompt: str, session: str) -> str:
        """VLM 视觉点击：截图 → 多模态 LLM 识别坐标 → CDP mouse 点击。"""
        import base64
        import re

        from ethan.browser.screenshot import save_screenshot
        from ethan.providers.base import Message
        from ethan.providers.manager import create_provider

        # 1. 截图
        result = await _call("page_screenshot", {"sessionId": session},
                             browser_session_id=session)
        saved = await save_screenshot(result)
        saved_obj = json.loads(saved)
        img_path = saved_obj.get("path", "")
        if not img_path:
            return json.dumps({"ok": False, "error": "截图失败"}, ensure_ascii=False)

        # 2. 读图 base64
        from pathlib import Path
        try:
            img_bytes = Path(img_path).read_bytes()
        except OSError as e:
            return json.dumps({"ok": False, "error": f"读取截图失败: {e}"}, ensure_ascii=False)
        img_b64 = base64.b64encode(img_bytes).decode()

        # 推断 media_type（webp/jpeg/png）
        ext = Path(img_path).suffix.lstrip('.')
        media_type = f"image/{ext}" if ext in ('webp', 'jpeg', 'jpg', 'png', 'gif') else "image/png"

        # 3. 调 VLM 定位坐标
        vlm_prompt = (
            f'在截图中找到"{prompt}"元素。'
            f'返回其中心点坐标（相对于视口左上角，CSS像素）。'
            f'只返回JSON，不要其他文字：{{"x": 数字, "y": 数字, "found": true/false, "reason": "简短说明"}}'
        )
        provider = create_provider()
        msg = Message(role="user", content=vlm_prompt,
                      images=[{"data": img_b64, "media_type": media_type}])
        try:
            resp = await provider.chat(messages=[msg], max_tokens=300)
        except Exception as e:
            return json.dumps({"ok": False, "error": f"VLM 调用失败: {e}",
                               "screenshot": img_path}, ensure_ascii=False)

        resp_text = resp.content if hasattr(resp, "content") else str(resp)
        # 4. 解析坐标
        m = re.search(r'\{[^}]+\}', resp_text)
        if not m:
            return json.dumps({"ok": False, "error": f"VLM 未返回有效坐标: {resp_text}",
                               "screenshot": img_path}, ensure_ascii=False)
        try:
            coords = json.loads(m.group())
        except json.JSONDecodeError:
            return json.dumps({"ok": False, "error": f"坐标解析失败: {m.group()}",
                               "screenshot": img_path}, ensure_ascii=False)
        if not coords.get("found", True):
            return json.dumps({"ok": False, "error": f"VLM 未找到目标: {prompt}",
                               "vlm_response": resp_text, "screenshot": img_path},
                              ensure_ascii=False)

        # 5. 点击
        x, y = coords["x"], coords["y"]
        await _click_point(session, x, y)
        return json.dumps({"ok": True, "vlm_prompt": prompt,
                           "coords": {"x": x, "y": y},
                           "screenshot": img_path,
                           "vlm_reason": coords.get("reason", "")},
                          ensure_ascii=False)

    def _enrich(self, result_str: str, action: str, session: str) -> str:
        """在返回 JSON 里注入 _hint（字段说明）和 _step（步数，仅交互动作）。

        原 _with_step 的步数逻辑并入这里，统一在出口处理，避免每个 action 单独包装。
        非 JSON 返回（如截断的 snapshot）走文字追加分支。
        """
        hint = _HINTS.get(action, "")
        step = None
        if action in _STEP_ACTIONS and session:
            step = get_session_map().increment_step(session)
        try:
            obj = json.loads(result_str)
            if isinstance(obj, dict):
                if hint:
                    obj["_hint"] = hint
                if step is not None:
                    obj["_step"] = step
                return json.dumps(obj, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass
        # 非 JSON 返回（如截断的 snapshot / 未知 action），追加文字说明
        parts = []
        if hint:
            parts.append(f"[说明] {hint}")
        if step is not None:
            parts.append(f"(step {step})")
        if parts:
            result_str += "\n" + " ".join(parts)
        return result_str


class BrowserNetworkTool(_BrowserToolBase):
    name = "browser_network"
    description = (
        "监控 session 的网络请求。start 开始抓包;stop 停止并清空;list 列出已捕获请求(可按 URL/类型过滤);"
        "detail 查看指定请求的详情(含响应体,最多 10000 字符)。"
        "常用场景:抓 API 响应数据代替从 DOM 里抠,排查请求失败原因。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "stop", "list", "detail"]},
            "session": {"type": "string", "description": "目标 session_id"},
            "filter": {"type": "string", "description": "list 时按 URL 或资源类型过滤(字符串包含匹配)"},
            "request_id": {"type": "string", "description": "detail 时的 requestId"},
        },
        "required": ["action", "session"],
    }

    async def run(self, action: str, session: str = "", filter: str = "", request_id: str = "") -> str:  # noqa: A002
        self._authorize()
        try:
            if action == "start":
                return json.dumps(await _call("network_start", {"sessionId": session}), ensure_ascii=False)
            if action == "stop":
                return json.dumps(await _call("network_stop", {"sessionId": session}), ensure_ascii=False)
            if action == "list":
                params: dict = {"sessionId": session}
                if filter:
                    params["filter"] = filter
                return json.dumps(await _call("network_list", params), ensure_ascii=False)
            if action == "detail":
                return json.dumps(await _call("network_detail", {"sessionId": session, "requestId": request_id}), ensure_ascii=False)
            return f"未知 action: {action}"
        except BrowserError as e:
            return f"浏览器错误: {e}" + (" (可重新 snapshot 后重试)" if e.retryable else "")
