"""Browser sessions implementation; browser.py keeps compatibility exports."""
from __future__ import annotations

import json

from ethan.browser.hub import BrowserError

from .browser_compat import browser as B
from .browser_runtime import _BrowserToolBase


class BrowserSessionTool(_BrowserToolBase):
    name = "browser_session"
    description = (
        "管理浏览器 session(一个 session 对应一个 Chrome Tab Group)。"
        "action=create 新建并打开 url;attach 获取已有 session 控制权(复用之前保留的);attach_current 接管当前 active tab;"
        "list 列出所有 session(含可复用的);rename 改名;update 更新标题和颜色;release 放掉控制权但保留 tab;close 关闭整个 tab group。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "attach", "attach_current", "list", "rename", "release", "close", "update"]},
            "session": {"type": "string", "description": "目标 session_id(attach/rename/release/close/update 必填;从 browser_session(action='list') 取)"},
            "url": {"type": "string", "description": "create 时打开的初始 URL"},
            "title": {"type": "string", "description": "session 标题(create/attach_current/rename)"},
            "color": {"type": "string", "description": "Tab Group 颜色（grey/blue/red/yellow/green/pink/purple/cyan/orange）"},
            "keep_alive": {"type": "boolean", "description": "create/attach/attach_current 时标记此 session 在对话结束后保留（不自动关闭 tab group）。默认 false（用完即关）。用户只是让帮个忙、页面还要继续看时设 true。"},
            "background": {"type": "boolean", "description": "create 时为 true 则在后台新窗口打开，不抢用户焦点。默认 true。设为 false 可在前台打开。"},
        },
        "required": ["action"],
    }

    async def run(self, action: str, session: str = "", url: str = "", title: str = "", color: str = "", keep_alive: bool = False, background: bool = True) -> str:
        self._authorize()
        try:
            # create/attach_current/list 是新建或全局操作,不需要既有 session;
            # attach/rename/release/close/update 需要一个目标 id,缺了提前说清楚。
            if action in ("attach", "rename", "release", "close", "update") and not session:
                return self._missing_session(action)
            if action == "create":
                params: dict = {}
                if url:
                    params["url"] = url
                if title:
                    params["title"] = title
                if color:
                    params["color"] = color
                if background:
                    params["background"] = True
                # 先 resolve 一次,路由和绑定共用这个值:_call 内部再 resolve 的话,
                # 两次之间状态可能变化(并行批里的 use / 瞬时掉线),绑错浏览器后
                # 后续操作会报「session not found」。
                client = B.get_hub().resolve_client(B.get_session_id())
                result = await B._call("session_create", params, client_name=client)
                bsid = B._extract_session_id(result)
                if bsid:
                    B.get_session_map().bind(bsid, B.get_session_id(),
                                           client_name=client or "", keep_alive=keep_alive)
                return json.dumps(result, ensure_ascii=False)
            if action == "attach":
                if not session:
                    return self._missing_session(action)
                # 先查清这个 session 到底在哪台浏览器上,再决定路由与绑定。
                # 必须用 _list_sessions_all_clients:它查全部在线客户端并带回 client 标注。
                # 过去这里用 _call("session_list", {}),那个走 resolve_client——两个客户端
                # 在线且未 use 时会直接抛「请先用 browser_client 选择一个」,把 attach 整个
                # 堵死(实测多浏览器会话里 attach 路径也因此不可用)。
                # 只读的跨客户端查询没有歧义,不该要求先选定客户端。
                list_result = await B._list_sessions_all_clients()
                target = None
                for s in list_result.get("sessions", []) or []:
                    if not isinstance(s, dict):
                        continue
                    sid = s.get("sessionId") or s.get("session_id")
                    if sid == session:
                        target = s
                        break
                if target is None:
                    return json.dumps({"error": f"session {session} 不存在，无法 attach"})
                # 以 session 实际所在的客户端为准,而不是当前活跃客户端:
                # attach 的是扩展里既有的 tab group,它物理上就在那台浏览器。
                client = target.get("client") or B.get_hub().resolve_client(B.get_session_id())
                if not client:
                    return json.dumps({"error": "没有可用的浏览器客户端"})
                # 校验归属：已被其他对话绑定时拒绝，避免覆盖式接管互相踩
                owner = B.get_session_map().get_owner(session)
                cur_sid = B.get_session_id()
                if owner and owner != cur_sid:
                    return json.dumps({"error": f"session {session} 正被其他会话使用，无法 attach"})
                B.get_session_map().bind(session, cur_sid,
                                       client_name=client, keep_alive=keep_alive)
                B.get_session_map().touch(session)
                return json.dumps({"attached": True, "sessionId": session, "client": client})
            if action == "attach_current":
                params = {}
                if title:
                    params["title"] = title
                if color:
                    params["color"] = color
                # 同 create:路由与绑定共用一次 resolve,防止两次之间状态漂移
                client = B.get_hub().resolve_client(B.get_session_id())
                result = await B._call("session_attach_current", params, client_name=client)
                bsid = B._extract_session_id(result)
                if bsid:
                    B.get_session_map().bind(bsid, B.get_session_id(),
                                           client_name=client or "", keep_alive=keep_alive)
                return json.dumps(result, ensure_ascii=False)
            if action == "list":
                result = await B._list_sessions_all_clients()
                return json.dumps(B._annotate_sessions(result), ensure_ascii=False)
            if action == "rename":
                return json.dumps(await B._call("session_rename", {"sessionId": session, "title": title},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "release":
                out = await B._call("session_release", {"sessionId": session}, browser_session_id=session)
                B.get_session_map().unbind(session)
                return json.dumps(out, ensure_ascii=False)
            if action == "close":
                out = await B._call("session_close", {"sessionId": session}, browser_session_id=session)
                B.get_session_map().unbind(session)
                return json.dumps(out, ensure_ascii=False)
            if action == "update":
                params = {"sessionId": session}
                if title:
                    params["title"] = title
                if color:
                    params["color"] = color
                return json.dumps(await B._call("session_update", params,
                                              browser_session_id=session), ensure_ascii=False)
            return f"未知 action: {action}"
        except BrowserError as e:
            return f"浏览器错误: {e}" + (" (可重新 snapshot 后重试)" if e.retryable else "")


class BrowserClientTool(_BrowserToolBase):
    name = "browser_client"
    # 默认(Fast 档)广播里就带上它:_call 的多客户端报错让 agent「先用
    # browser_client(use) 选择」,若这个工具本身还要 find_tools 激活,
    # 提示就成了无法执行的空话。
    fast_path = True
    description = (
        "管理浏览器客户端连接。多个浏览器可同时连接 Ethan Server,每个有自己的名字。"
        "action=list 列出所有已连接的浏览器客户端(含名称、各自当前活动标签页、本对话在其上的 session);"
        "use 设置当前对话使用哪个客户端(name 必填);"
        "status 查看当前对话的活跃客户端和全部已连接客户端。"
        "当有多个浏览器连接时,新建 session 前需先用 use 选择一个;仅一个连接时自动使用它。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "use", "status"]},
            "name": {"type": "string", "description": "use 时的客户端名称(从 list 结果中取)"},
        },
        "required": ["action"],
    }

    async def run(self, action: str, name: str = "") -> str:
        self._authorize()
        hub = B.get_hub()
        try:
            if action == "list":
                clients = await B._describe_clients()
                return json.dumps({
                    "clients": clients,
                    "active": hub.get_active_client(B.get_session_id()),
                    "_hint": B._clients_hint(clients),
                }, ensure_ascii=False)
            if action == "use":
                if not name:
                    return json.dumps({
                        "ok": False,
                        "error": "use 需要 name 参数。用 action=list 查看已连接的客户端。",
                    }, ensure_ascii=False)
                ok = hub.set_active_client(B.get_session_id(), name)
                if ok:
                    # 汇报名下 session 的分布:切客户端只影响「新建/无 session 操作」的路由,
                    # 既有 session 仍按绑定路由到原浏览器(tab group 物理在那边)。
                    # 不清理绑定:session 的 tab 还在旧浏览器里,清掉映射只会让
                    # idle 回收(release)失去目标,留下孤儿 tab group。
                    bound = B.get_session_map().owned_by_client(B.get_session_id())
                    elsewhere = {c: ids for c, ids in sorted(bound.items()) if c and c != name}
                    result: dict = {
                        "ok": True,
                        "active": name,
                        "bound_sessions_here": sorted(bound.get(name, [])),
                    }
                    hint = (f"已切换到客户端 '{name}'。后续新建 session 与browser_tab/user_list 等无 session 操作都会路由到这个浏览器。")
                    if elsewhere:
                        total = sum(len(v) for v in elsewhere.values())
                        result["bound_sessions_elsewhere"] = elsewhere
                        hint += (
                            f" 注意:本对话还有 {total} 个既有 browser session 在旧客户端（{'、'.join((f'{c} {len(ids)} 个' for c, ids in elsewhere.items()))}）,操作它们仍会路由到原浏览器;若要在当前浏览器继续同样的页面,请新建 session 或让用户把标签页挪过来。"
                        )
                    result["_hint"] = hint
                    return json.dumps(result, ensure_ascii=False)
                clients = hub.list_clients()
                names = [c["name"] for c in clients]
                return json.dumps({
                    "ok": False,
                    "error": f"客户端 '{name}' 未连接。",
                    "available": names,
                    "_hint": "可用客户端: " + ", ".join(names) if names else "没有已连接的客户端",
                }, ensure_ascii=False)
            if action == "status":
                clients = await B._describe_clients()
                active = hub.get_active_client(B.get_session_id())
                hint = f"当前活跃: {active}" if active else B._clients_hint(clients)
                return json.dumps({
                    "active": active,
                    "clients": clients,
                    "_hint": hint,
                }, ensure_ascii=False)
            return f"未知 action: {action}"
        except BrowserError as e:
            return f"浏览器错误: {e}"
