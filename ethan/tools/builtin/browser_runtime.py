"""Browser runtime implementation; browser.py keeps compatibility exports."""
from __future__ import annotations

import json
import time

from ethan.browser.hub import BrowserError
from ethan.browser.protocol import ERROR_CODE, METHODS
from ethan.tools.base import BaseTool

from .browser_compat import browser as B

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
    "eval": (
        "已执行页面 JS。result 字段是脚本返回值（若有）。"
        "result_truncated=true 时结果过大、已截断：首段在 result 字段，完整内容落盘在 result_path。"
        "读取后续用 snapshot_read(action=snapshot_read, path=result_path, offset=result_chunk_length)——"
        "注意 snapshot_read 的续段文本在返回的 snapshot 字段里（不是 result），"
        "下一页用它返回的 offset+chunk_length，has_more=false 表示读完。"
        "抓大列表时建议脚本内先筛选/精简字段（如只留标题+关键指标），减少无谓翻页。"
    ),
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
    "organize": (
        "已应用 tab 整理操作。applied 字段说明实际执行了什么;skipped 是因 tab 消失等原因跳过的条目。"
        "整理后会自动折叠涉及的 TabGroup(applied.collapsed),但**跳过用户当前活跃的那一组**"
        "(applied.collapseSkipped)——那一组保持展开。折叠失败的组在 applied.collapseFailed。"
        "若用了 rest/rest_group/rest_auto,applied.rest 说明休息结果:"
        "rested 是实际释放了内存的 tab,restSkipped 是按规则有意没动的(附原因,"
        "如「是当前正在看的标签」「是今天打开的」),restFailed 是尝试了但失败的。"
    ),
}


async def _call(method_key: str, params: dict, browser_session_id: str | None = None,
                *, client_name: str | None = None):
    """发起 browser RPC。自动解析目标客户端:
    - 操作既有 browser_session_id → 从 session_map 取该 session 所属客户端
    - 新建/列表等无 session_id 的操作 → 用当前 ethan 会话的活跃客户端

    当有多个客户端连接且未设活跃时,抛出明确错误提示 agent 询问用户。

    client_name:调用方预解析好的目标客户端。create/attach_current 必须「路由到谁
    就把新 session 绑给谁」——若路由和绑定各 resolve 一次,两次之间状态可能变化
    (并行批次里的 use、瞬时掉线),绑错/绑空后该 session 就再也找不到归属。
    """
    smap = B.get_session_map()
    hub = B.get_hub()
    ethan_sid = B.get_session_id()

    if client_name is None:
        # 会话隔离门禁:凡是操作既有 browser session 的调用,该 session 必须属于当前 ethan 会话。
        # 若绑定关系丢失(例如 ethan 重启、对话换 ID),允许先向扩展核实 session 真实存在且
        # 未被其他 ethan 会话占用,再自动恢复绑定,避免用户明明在「这个」tab 上操作却被拒。
        if browser_session_id is not None:
            client_name = await B._require_owned_or_recover(browser_session_id, ethan_sid)
            if not client_name:
                client_name = hub.resolve_client(ethan_sid)
        else:
            client_name = hub.resolve_client(ethan_sid)
            if client_name is None:
                clients = hub.list_clients()
                if not clients:
                    raise BrowserError(
                        "浏览器扩展未连接,请确认已安装并启用扩展",
                        code=ERROR_CODE["extension_not_connected"],
                        retryable=False,
                    )
                names = [c["name"] for c in clients]
                raise BrowserError(
                    f"当前有 {len(clients)} 个浏览器客户端已连接: {', '.join(names)}。请先用 browser_client(action='use', name='客户端名称') 选择一个,或直接告诉用户你想操作哪个浏览器。也可以用 browser_client(action='list') 查看详情。",
                    code=ERROR_CODE["extension_not_connected"],
                    retryable=False,
                )

    result = await hub.call(METHODS[method_key], params,
                            client_name=client_name, browser_session_id=browser_session_id)
    if browser_session_id:
        smap.touch(browser_session_id)
    return result


async def _require_owned_or_recover(browser_session_id: str, ethan_sid: str) -> str | None:
    """校验 browser session 归属当前 ethan 会话;不归属时尝试恢复绑定。

    返回该 session 所在的客户端名称(通常非空,除非扩展也找不到它),以便调用方
    不用再去二次 resolve。未通过校验且恢复失败则抛出 BrowserError。
    """
    if not browser_session_id:
        # 调用方漏传 session,不是归属问题。这两者过去共用同一句报错,把模型
        # 引向了错误的方向:实测一次多浏览器标签整理会话里模型看到「不属于当前
        # 对话」后,一路去 attach_current / 切换浏览器 / 重读技能,整整 30 步都
        # 没意识到自己只是漏了个参数。这里改成可执行的自查提示,并说清去哪取 id。
        raise BrowserError(
            "缺少 session 参数:本操作需要指定要操作的 browser session。"
            "请先用 browser_session(action='list') 取 sessionId,再带上 session= 重试。",
            code=ERROR_CODE["invalid_params"],
            retryable=False,
        )
    smap = B.get_session_map()
    owned = smap.list_for(ethan_sid)
    if browser_session_id in owned and smap.get_client(browser_session_id):
        return smap.get_client(browser_session_id)
    # owned 但没记客户端名(绑定成 "" 的历史数据)同样走探针:按当前活跃客户端猜
    # 很容易猜错浏览器,错了扩展会报「session not found」,用户看到的是凭空失败。

    # --- 绑定关系丢失:向扩展核实 session 是否真的存在 ---
    hub = B.get_hub()
    # 优先用当前 ethan 会话的活跃客户端去查(大多时候会话就在这个浏览器里)
    probe_clients: list[str] = []
    active = hub.get_active_client(ethan_sid)
    if active:
        probe_clients.append(active)
    for name, conn in getattr(hub, "_conns", {}).items():
        if not getattr(conn, "closed", True) and name not in probe_clients:
            probe_clients.append(name)

    found_client: str | None = None
    for cname in probe_clients:
        try:
            res = await hub.call(METHODS["session_list"], {}, client_name=cname)
        except Exception:
            continue
        sessions = res.get("sessions") if isinstance(res, dict) else None
        if not isinstance(sessions, list):
            continue
        if any(
            isinstance(s, dict)
            and (s.get("sessionId") or s.get("session_id")) == browser_session_id
            for s in sessions
        ):
            found_client = cname
            break

    if found_client is None:
        # 扩展侧也确实找不到这个 session,正常拒绝
        raise BrowserError(
            "该 browser session 不属于当前对话,拒绝操作",
            code=ERROR_CODE["session_not_found"],
        )

    # 扩展确认 session 存在即可恢复绑定。
    # 单用户场景下不同对话操作同一 tab 是正常行为，无需防跨对话抢占。
    # keep_alive 沿用原值:回填只是补客户端名,不能顺手把「对话结束保留」标志冲掉。
    smap.bind(browser_session_id, ethan_sid, client_name=found_client,
              keep_alive=smap.is_keep_alive(browser_session_id))
    return found_client


def _require_owned(browser_session_id: str) -> None:
    """同步版本的归属校验(仅用于无需恢复绑定的调用点,保持兼容)。"""
    owned = B.get_session_map().list_for(B.get_session_id())
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


def _annotate_sessions(result: dict | None) -> dict:
    """session_list 结果标注归属：owned=当前对话绑定的，available=可通过 attach 复用的。"""
    result = result or {}
    owned = set(B.get_session_map().list_for(B.get_session_id()))
    sessions = result.get("sessions")
    if isinstance(sessions, list):
        annotated = []
        for s in sessions:
            if not isinstance(s, dict):
                continue
            sid = s.get("sessionId") or s.get("session_id")
            s_copy = dict(s)
            s_copy["status"] = "owned" if sid in owned else "available"
            annotated.append(s_copy)
        return {**result, "sessions": annotated}
    return result


# active_tab 查询结果短缓存:list/status 每次都对每个客户端发一次 tabs.userList,
# agent 连续几轮调用时不必每次都真实过网。仅用于展示,5s 内的轻微陈旧可接受。
_ACTIVE_TAB_TTL = 5.0
_active_tab_cache: dict[str, tuple[float, dict | None]] = {}


async def _describe_clients() -> list[dict]:
    """给客户端列表补上「可分辨」信息——随机名分不清哪台是哪台是多浏览器误操作的根源。

    每个客户端追加:
      - owned_sessions: 当前对话绑定在该客户端上的 browser session id 列表(零 RPC)
      - active_tab: 该浏览器当前活动标签页的 {title, host}(实时 RPC,失败则省略该字段)
    """
    import asyncio
    from urllib.parse import urlparse

    hub = B.get_hub()
    owned = B.get_session_map().owned_by_client(B.get_session_id())

    async def _active_tab(client_name: str) -> dict | None:
        cached = B._active_tab_cache.get(client_name)
        now = time.monotonic()
        if cached and now - cached[0] < B._ACTIVE_TAB_TTL:
            return cached[1]
        try:
            res = await hub.call(METHODS["tab_user_list"], {},
                                 client_name=client_name, timeout=3)
        except Exception:
            return cached[1] if cached else None
        tabs = res.get("tabs") if isinstance(res, dict) else None
        tab: dict | None = None
        if isinstance(tabs, list):
            for t in tabs:
                if isinstance(t, dict) and t.get("active"):
                    url = t.get("url") or ""
                    tab = {"title": t.get("title") or "",
                           "host": urlparse(url).netloc if url else ""}
                    break
        B._active_tab_cache[client_name] = (now, tab)
        return tab

    clients = sorted(hub.list_clients(), key=lambda c: c["name"])
    tab_results = await asyncio.gather(*[_active_tab(c["name"]) for c in clients])
    for c, tab in zip(clients, tab_results):
        c["owned_sessions"] = owned.get(c["name"], [])
        if tab:
            c["active_tab"] = tab
    return clients


def _clients_hint(clients: list[dict]) -> str:
    """根据客户端描述生成给 agent 的选择指引。"""
    if not clients:
        return ("没有浏览器客户端连接。请确认已安装并启用 Ethan Browser 扩展。")
    mine = {c["name"]: c.get("owned_sessions") or [] for c in clients
            if c.get("owned_sessions")}
    parts = [f"共 {len(clients)} 个客户端已连接。"]
    if mine:
        for n, ids in mine.items():
            parts.append(f"本对话的 browser session 在 '{n}' 上（{len(ids)} 个），操作既有 session 不受 use 影响。")
        others = [c["name"] for c in clients if c["name"] not in mine]
        if others:
            parts.append(f"{'、'.join(others)} 没有本对话的会话，新建 session 前先用 use 选定。")
    else:
        parts.append("本对话还没有绑定任何 browser session。")
        if len(clients) > 1:
            parts.append("请结合各客户端的 active_tab（用户当前页面）判断要操作哪个浏览器，"
                         "分不清就直接问用户。")
    return " ".join(parts)


async def _list_sessions_all_clients() -> dict:
    """session_list 查询**所有**在线客户端并合并，每条 session 标注所属客户端。

    只查活跃客户端时，另一个浏览器里的 session 对 agent 完全不可见，会被误判为
    「不存在」而重新 create，在用户浏览器里留下重复的 tab group。只读操作无歧义，
    多客户端时全部查询。
    """
    import asyncio

    hub = B.get_hub()
    online = sorted(c["name"] for c in hub.list_clients())
    if not online:
        raise BrowserError(
            "浏览器扩展未连接,请确认已安装并启用扩展",
            code=ERROR_CODE["extension_not_connected"],
            retryable=False,
        )

    async def _one(client_name: str) -> tuple[str, dict | None, str]:
        try:
            res = await hub.call(METHODS["session_list"], {},
                                 client_name=client_name, timeout=5)
            return client_name, (res if isinstance(res, dict) else None), ""
        except Exception as e:
            return client_name, None, str(e)

    merged: list[dict] = []
    seen: set[str] = set()
    errors: list[str] = []
    for client_name, res, err in await asyncio.gather(*[_one(n) for n in online]):
        if res is None:
            errors.append(f"{client_name}: {err or '无结果'}")
            continue
        for s in res.get("sessions") or []:
            if not isinstance(s, dict):
                continue
            sid = s.get("sessionId") or s.get("session_id")
            if sid and sid in seen:
                continue
            if sid:
                seen.add(sid)
            merged.append({**s, "client": client_name})
    out: dict = {"sessions": merged}
    if errors:
        out["_errors"] = errors
    return out


def _consent_desc() -> str | None:
    """会话级门禁:已授权返回 None(放行),否则返回授权说明触发 consent。"""
    if B.is_authorized(B.get_session_id()):
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
        return B._consent_desc()

    def _authorize(self) -> None:
        B.mark_authorized(B.get_session_id())

    def _missing_session(self, action: str) -> str:
        """缺少 session 参数时的统一返回。

        过去这种情况会落到归属校验里,报出「该 browser session 不属于当前对话」,
        模型据此以为归属出错,转而去 attach_current / 切换浏览器,始终没发现自己
        只是漏了参数(实测一次多浏览器标签整理会话因此空转 30 步)。这里直接点明缺什么、
        去哪取,给一条可执行的下一步。
        """
        return json.dumps({
            "error": f"{action} 需要 session 参数,当前未提供。",
            "_hint": (
                "本操作必须指定要操作的 browser session。"
                "先调 browser_session(action='list') 取 sessionId"
                "(返回的每条含 status: owned=本对话已绑定,可用),再带上 session=<sessionId> 重试。"
                "若 list 为空,说明本对话还没有 tab group,"
                "用 browser_session(action='create', url=...) 新建,"
                "或 browser_session(action='attach_current') 接管当前标签页。"
            ),
        }, ensure_ascii=False)

