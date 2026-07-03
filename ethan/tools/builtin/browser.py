"""Browser 工具 —— agent 通过这三个工具操作本机 Chrome(经 BrowserHub → 扩展 → CDP)。

  browser_session : create / attach_current / list / rename / release / close
  browser_tab     : open / list / user_list / attach / active / activate / close
  browser_page    : snapshot / click / fill / type / press / hover / select /
                    scroll / scroll_into_view / screenshot / get / mouse / wait / eval

授权(方案 Q6):会话级一次性。某 ethan 会话首次调用任意 browser 工具触发一次 consent,
批准后该会话内全部 browser 操作(含 eval)放行。consent_check 读当前会话授权态;
run() 在 consent 通过后调用,开头 mark_authorized。
"""
from __future__ import annotations

import json

from ethan.browser.auth import is_authorized, mark_authorized
from ethan.browser.hub import BrowserError, get_hub
from ethan.browser.protocol import ERROR_CODE, METHODS
from ethan.browser.session_map import get_session_map
from ethan.core.context import get_session_id
from ethan.tools.base import BaseTool

# snapshot 硬截断安全网(方案 Q7):防止复杂页面 AX 树打爆上下文。
_SNAPSHOT_MAX_CHARS = 30000


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
        "list 列出 session;rename 改名;release 放掉控制权但保留 tab;close 关闭整个 tab group。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "attach_current", "list", "rename", "release", "close"]},
            "session": {"type": "string", "description": "目标 session_id(rename/release/close 必填)"},
            "url": {"type": "string", "description": "create 时打开的初始 URL"},
            "title": {"type": "string", "description": "session 标题(create/attach_current/rename)"},
        },
        "required": ["action"],
    }

    async def run(self, action: str, session: str = "", url: str = "", title: str = "") -> str:
        self._authorize()
        try:
            if action == "create":
                params: dict = {}
                if url:
                    params["url"] = url
                if title:
                    params["title"] = title
                result = await _call("session_create", params)
                bsid = _extract_session_id(result)
                if bsid:
                    get_session_map().bind(bsid, get_session_id())
                return json.dumps(result, ensure_ascii=False)
            if action == "attach_current":
                params = {"title": title} if title else {}
                result = await _call("session_attach_current", params)
                bsid = _extract_session_id(result)
                if bsid:
                    get_session_map().bind(bsid, get_session_id())
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
            return f"未知 action: {action}"
        except BrowserError as e:
            return f"浏览器错误: {e}" + (" (可重新 snapshot 后重试)" if e.retryable else "")


class BrowserTabTool(_BrowserToolBase):
    name = "browser_tab"
    description = (
        "管理 session 内的 tab。open 新开 tab;list 列出 session 内 tab;"
        "user_list 列出用户所有 tab;attach 把已有 tab 纳入 session;"
        "active 取当前活动 tab;activate 切换活动 tab;close 关闭 tab。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["open", "list", "user_list", "attach", "active", "activate", "close"]},
            "session": {"type": "string", "description": "目标 session_id"},
            "tab": {"type": "string", "description": "目标 tab_id(attach/activate/close)"},
            "url": {"type": "string", "description": "open 时打开的 URL"},
        },
        "required": ["action"],
    }

    async def run(self, action: str, session: str = "", tab: str = "", url: str = "") -> str:
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
            if action == "attach":
                return json.dumps(await _call("tab_attach", {"sessionId": session, "tabId": tab},
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
            return f"未知 action: {action}"
        except BrowserError as e:
            return f"浏览器错误: {e}" + (" (可重新 snapshot 后重试)" if e.retryable else "")


class BrowserPageTool(_BrowserToolBase):
    name = "browser_page"
    description = (
        "操作 session 的 active tab。snapshot 取页面 AX 树+ref(默认 interactive+compact);"
        "click/fill/type/press/hover/select/scroll_into_view 用 ref 交互;"
        "scroll 滚动;mouse 发坐标级鼠标事件;get 读 title/url/text/value/html/box;"
        "screenshot 截图;wait 等待;eval 执行页面 JS(高权限)。"
        "ref 仅对最近一次 snapshot 可靠,页面跳转/刷新后需重新 snapshot。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [
                "snapshot", "click", "fill", "type", "press", "hover", "select",
                "scroll", "scroll_into_view", "screenshot", "get", "mouse", "wait", "eval",
            ]},
            "session": {"type": "string", "description": "目标 session_id"},
            "ref": {"type": "string", "description": "snapshot 返回的元素 ref(click/fill/type/hover/select/get/scroll_into_view)"},
            "text": {"type": "string", "description": "fill/type 输入的文本"},
            "key": {"type": "string", "description": "press 的按键,如 Enter"},
            "value": {"type": "string", "description": "select 的选项值"},
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
            "selector": {"type": "string", "description": "snapshot 限定 DOM 子树的 CSS 选择器"},
            "cursor": {"type": "boolean", "description": "snapshot 补充 cursor:pointer/onclick 元素"},
            "urls": {"type": "boolean", "description": "snapshot 包含链接 href"},
            "format": {"type": "string", "enum": ["text", "json"], "description": "snapshot 输出格式"},
        },
        "required": ["action", "session"],
    }

    async def run(self, action: str, session: str = "", **kw) -> str:
        self._authorize()
        # 计步动作（交互/变更类）；snapshot/get/wait/screenshot 不计步
        _STEP_ACTIONS = {"click", "fill", "type", "press", "hover", "select",
                         "scroll", "scroll_into_view", "mouse", "eval"}

        def _with_step(result_str: str) -> str:
            """把当前步数追加到 JSON 响应里，让模型感知步数预算。"""
            if action not in _STEP_ACTIONS or not session:
                return result_str
            steps = get_session_map().increment_step(session)
            try:
                obj = json.loads(result_str)
                if isinstance(obj, dict):
                    obj["_step"] = steps
                    return json.dumps(obj, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass
            return result_str + f'  <!-- step {steps} -->'

        try:
            if action == "snapshot":
                params = {"sessionId": session}
                for k in ("interactive", "compact", "depth", "selector", "cursor", "urls", "format"):
                    if kw.get(k) is not None:
                        params[k] = kw[k]
                result = await _call("page_snapshot", params, browser_session_id=session)
                out = json.dumps(result, ensure_ascii=False)
                if len(out) > _SNAPSHOT_MAX_CHARS:
                    return (out[:_SNAPSHOT_MAX_CHARS]
                            + "\n...(快照过大已截断。请用 selector 限定区域、降低 depth、"
                              "或加 interactive=true/compact=true 后重试)")
                return out
            if action == "click":
                return _with_step(json.dumps(await _call("page_click", {"sessionId": session, "ref": kw.get("ref")},
                                              browser_session_id=session), ensure_ascii=False))
            if action == "fill":
                return _with_step(json.dumps(await _call("page_fill", {"sessionId": session, "ref": kw.get("ref"), "text": kw.get("text", "")},
                                              browser_session_id=session), ensure_ascii=False))
            if action == "type":
                return _with_step(json.dumps(await _call("page_type", {"sessionId": session, "ref": kw.get("ref"), "text": kw.get("text", "")},
                                              browser_session_id=session), ensure_ascii=False))
            if action == "press":
                return _with_step(json.dumps(await _call("page_press", {"sessionId": session, "key": kw.get("key")},
                                              browser_session_id=session), ensure_ascii=False))
            if action == "hover":
                return _with_step(json.dumps(await _call("page_hover", {"sessionId": session, "ref": kw.get("ref")},
                                              browser_session_id=session), ensure_ascii=False))
            if action == "select":
                return _with_step(json.dumps(await _call("page_select", {"sessionId": session, "ref": kw.get("ref"), "value": kw.get("value")},
                                              browser_session_id=session), ensure_ascii=False))
            if action == "scroll_into_view":
                return _with_step(json.dumps(await _call("page_scroll_into_view", {"sessionId": session, "ref": kw.get("ref")},
                                              browser_session_id=session), ensure_ascii=False))
            if action == "scroll":
                params = {"sessionId": session, "direction": kw.get("direction", "down")}
                if kw.get("pixels") is not None:
                    params["pixels"] = kw["pixels"]
                return _with_step(json.dumps(await _call("page_scroll", params, browser_session_id=session), ensure_ascii=False))
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
                return _with_step(json.dumps(await _call("page_mouse", params, browser_session_id=session), ensure_ascii=False))
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
            if action == "eval":
                return _with_step(json.dumps(await _call("page_eval", {"sessionId": session, "script": kw.get("script", "")},
                                              browser_session_id=session), ensure_ascii=False))
            return f"未知 action: {action}"
        except BrowserError as e:
            return f"浏览器错误: {e}" + (" (可重新 snapshot 后重试)" if e.retryable else "")
