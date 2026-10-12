"""Browser tabs implementation; browser.py keeps compatibility exports."""
from __future__ import annotations

import json

from ethan.browser.hub import BrowserError

from .browser_compat import browser as B
from .browser_runtime import _BrowserToolBase


class BrowserTabTool(_BrowserToolBase):
    name = "browser_tab"
    description = (
        "管理 session 内的 tab。open 新开 tab;list 列出 session 内 tab;"
        "user_list 列出用户所有 tab;find_tab 按关键词在已开 tab 里搜索(匹配 title 和 url,"
        "空格分隔多词,任一命中即返回候选列表;active_only=true 取用户当前活动 tab);"
        "attach 把已有 tab 纳入 session;attach_batch 批量把多个 tab 纳入 session;"
        "active 取当前活动 tab;activate 切换活动 tab;close 关闭 tab;"
        "detach 把 tab 移出 session(取消分组但不关闭);move 调整 tab 在组内的位置。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["open", "list", "user_list", "find_tab", "attach", "attach_batch", "active", "activate", "close", "detach", "move", "organize"]},
            "session": {"type": "string", "description": "目标 session_id(除 user_list/find_tab 外必填;从 browser_session(action='list') 取)"},
            "tab": {"type": "string", "description": "目标 tab_id(attach/activate/close;从 browser_tab(action='user_list'/'list') 结果取 tabId)"},
            "url": {"type": "string", "description": "open 时打开的 URL;find_tab 时也可直接填网址当关键词(等价 query)"},
            "active_only": {"type": "boolean", "description": "find_tab 专用:true=只返回用户当前活动的 tab,忽略关键词"},
            "query": {
                "type": "string",
                "description": (
                    "find_tab 专用:搜索关键词,空格分隔多个词。"
                    "按 title 和 url 双字段匹配,大小写不敏感,任一命中即算匹配(OR),"
                    "按命中词数+相关度排序返回候选。搜「标题里有 XX 的页面」用这个,"
                    "比用 url 匹配有效——很多页面 URL 里没有标题里的词。"
                ),
            },
            "limit": {"type": "integer", "description": "find_tab 专用:最多返回几个候选,默认 10,上限 50"},
            "tabs": {"type": "array", "items": {"type": "string"}, "description": "attach_batch 时的 tab_id 列表"},
            "index": {"type": "integer", "description": "move 时的目标位置索引"},
            "ops": {
                "type": "array",
                "description": (
                    "organize 专用。每个元素是一个操作:"
                    '{"op":"close","tabs":[tabId,...]} 关闭这些 tab;'
                    '{"op":"group","title":"组名","tabs":[tabId,...],"color":"blue","groupId":N} 把这些 tab 放进指定组(groupId 或 title 找到已有组;都没提供则新建);'
                    '{"op":"ungroup","tabs":[tabId,...]} 把这些 tab 移出所属组;'
                    '{"op":"ungroup_all","groupId":N} 解散整个组(groupId 或 title 指定);'
                    '{"op":"rest","tabs":[tabId,...]} 让这些 tab 休息(释放内存,标题保留,点开时重新加载);'
                    '{"op":"rest_group","groupId":N} 整组休息;'
                    '{"op":"rest_auto","groupId":N} 整组里「昨天及更早打开的」才休息。'
                    "op 顺序应用;tab 已消失则跳过(不报错)。"
                    "「休息」的代价:页面会重新加载,填了一半的表单/滚动位置会丢。"
                    "因此活跃 tab、正在播放声音的、固定住的、正被 session 或调试器使用的、"
                    "以及内部页/本地文件/本地服务一律不动,会记在 rest.restSkipped 里说明原因。"
                ),
                "items": {"type": "object"},
            },
            "collapse": {
                # "auto"/"none" 字符串与布尔都合法(扩展侧同样接受),
                # 只声明 boolean 会让模型无法表达 auto/none 这两个语义。
                "type": ["boolean", "string"],
                "enum": [True, False, "auto", "none"],
                "description": (
                    "organize 专用:整理完成后是否折叠本次涉及的 TabGroup。"
                    "不传或 'auto'(默认)=自动折叠,但跳过包含当前活跃 tab 的组"
                    "(不会把用户正在看的那组收起来);"
                    "'none' 或 false=完全不折叠;true=强制全部折叠(含活跃组)。"
                ),
            },
            "rest_mode": {
                "type": "string",
                "enum": ["yesterday", "off"],
                "description": (
                    "organize 专用:「按时间自动休息」的档位。"
                    "不传时跟随扩展设置(popup 里的「旧标签自动休息」开关,默认开启)。"
                    "'yesterday'=把昨天及更早打开、今天没碰过、且不在保护名单里的 tab 释放内存;"
                    "'off'=只处理显式指定的 rest/rest_group,不做按时间的自动休息。"
                    "注意只有 rest_auto op 才会走这个档位判断。"
                ),
            },
        },
        "required": ["action"],
    }

    async def run(self, action: str, session: str = "", tab: str = "", url: str = "", active_only: bool = False, tabs: list = None, index: int = -1, ops: list = None, collapse: bool | str = None, rest_mode: str = None, query: str = "", limit: int = None) -> str:
        self._authorize()
        try:
            # 提前拦缺参:只有 user_list/find_tab 是全局的,其余都要 session。
            # 不拦的话会一路走到 _require_owned_or_recover,过去那里报的是
            # 「不属于当前对话」,把「漏传参数」误导成「归属出错」。
            if action not in ("user_list", "find_tab", "organize") and not session:
                return self._missing_session(action)
            if action == "open":
                return json.dumps(await B._call("tab_open", {"sessionId": session, "url": url},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "list":
                return json.dumps(await B._call("tab_list", {"sessionId": session},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "user_list":
                # 全量 tab 清单可能很长（几十个 tab，title 也可能很长），必须做
                # 容量保护：超限时**完整清单落盘**并把首段返回给模型，同时打上
                # total/returned/truncated/path 标记。没有这层保护时，超长返回值
                # 会被上层链路静默截断——模型只看到前几条 tab 却以为是全部，
                # 据此做 tab 整理必然漏 tab（真实踩过的坑）。
                raw = await B._call("tab_user_list", {})
                return B._pack_user_tabs(raw)
            if action == "find_tab":
                # 匹配下沉到扩展侧（tabs.search）：tab 数据本来就只在那里。
                # 早期版本是把全量 tab 拉回 Python 做子串匹配——那是把数据搬到
                # 计算处而不是反过来，tab 一多传输量大，而且只搜 url、只回第一条。
                #
                # query 和 url 都当关键词用（url 更符合「我知道网址」的直觉，
                # query 更符合「我记得标题」；两者都走同一套切词+打分）。
                keywords = " ".join(x for x in (query, url) if x).strip()
                payload = {}
                if keywords:
                    payload["query"] = keywords
                if active_only:
                    payload["activeOnly"] = True
                if limit is not None:
                    payload["limit"] = limit
                result = await B._call("tab_search", payload)
                if not isinstance(result, dict):
                    return json.dumps({"found": False, "matches": [], "total": 0},
                                      ensure_ascii=False)
                matches = result.get("matches") or []
                if not matches:
                    return json.dumps({
                        "found": False,
                        "matches": [],
                        "total": 0,
                        "hint": "没有匹配的 tab。可用 browser_tab(action='user_list') 看全部已开 tab。",
                    }, ensure_ascii=False)
                # 直接回候选列表，不再额外挑一条当「答案」：用户说「那个 XX 页面」
                # 时往往不是第一个命中的，只回一条会让模型挑错还没得选。
                out = {
                    "found": True,
                    "matches": matches,
                    "total": result.get("total", len(matches)),
                    "scanned": result.get("scanned", 0),
                }
                if result.get("truncated"):
                    out["hint"] = (
                        f"共匹配 {result.get('total')} 个,已按相关度截断展示。用 limit 调大,或加关键词收窄。"
                    )
                return json.dumps(out, ensure_ascii=False)
            if action == "attach":
                return json.dumps(await B._call("tab_attach", {"sessionId": session, "tabId": tab},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "attach_batch":
                tab_ids = tabs or []
                return json.dumps(await B._call("tab_attach_batch", {"sessionId": session, "tabIds": tab_ids},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "active":
                return json.dumps(await B._call("tab_active", {"sessionId": session},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "activate":
                return json.dumps(await B._call("tab_activate", {"sessionId": session, "tabId": tab},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "close":
                return json.dumps(await B._call("tab_close", {"sessionId": session, "tabId": tab},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "detach":
                return json.dumps(await B._call("tab_detach", {"sessionId": session, "tabId": tab},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "move":
                return json.dumps(await B._call("tab_move", {"sessionId": session, "tabId": tab, "index": index},
                                              browser_session_id=session), ensure_ascii=False)
            if action == "organize":
                if ops is None:
                    return json.dumps({"error": "organize 需要 ops 参数（未传）"}, ensure_ascii=False)
                if ops == []:
                    return json.dumps({"error": "organize 的 ops 数组为空，至少需要一个操作"}, ensure_ascii=False)
                # 不传 collapse → 扩展侧按 'auto' 处理（折叠但跳过活跃组）。
                # 传字符串时原样透传（'auto'/'none'），布尔同理。
                payload = {"ops": ops}
                if collapse is not None:
                    payload["collapse"] = collapse
                # 不传 rest_mode → 扩展侧读 popup 的开关（默认开启）。
                if rest_mode is not None:
                    payload["restMode"] = rest_mode
                return json.dumps(await B._call("tab_organize", payload), ensure_ascii=False)
            return f"未知 action: {action}"
        except BrowserError as e:
            return f"浏览器错误: {e}" + (" (可重新 snapshot 后重试)" if e.retryable else "")

