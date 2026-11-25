"""producer browser responsibilities; imported via producers facade."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

async def _close_browser_sessions(session_id: str | None, run=None) -> None:
    """清理当前 ethan 会话创建的所有 browser session（tab group）。

    对话结束后调用。keep_alive 的 session 直接 release（保留 tab）。
    其余 session 弹卡片让用户确认是「关闭」还是「保留」，超时默认保留。
    """
    if not session_id:
        return
    try:
        from ethan.browser.hub import get_hub
        from ethan.browser.protocol import METHODS
        from ethan.browser.session_map import get_session_map

        smap = get_session_map()
        hub = get_hub()
        if not hub.connected:
            return

        bsids = smap.list_for(session_id)
        if not bsids:
            return

        # keep_alive 的直接 release，不弹卡片
        to_confirm: list[dict] = []
        for bsid in bsids:
            client_name = smap.get_client(bsid)
            if not client_name:
                smap.unbind(bsid)
                continue
            if smap.is_keep_alive(bsid):
                # release 是真放权：通知扩展「ethan 不再管这个 session」，扩展侧同步
                # 不再把它算作受控 session。这里 unbind 与扩展状态一致，是对的——
                # 与下面 keep 分支的区别就在这里：keep 只是 ethan 自己收尾，扩展仍追踪，
                # 所以 keep 绝不能 unbind（否则 ethan 失忆、扩展还记得，两边对不上）。
                try:
                    await hub.call(
                        METHODS["session_release"],
                        {"sessionId": bsid},
                        client_name=client_name,
                        browser_session_id=bsid,
                    )
                except Exception:
                    logger.warning("browser: release keep_alive session failed for %s", bsid)
                finally:
                    smap.unbind(bsid)
            else:
                to_confirm.append({"sessionId": bsid, "title": "", "tabCount": 0, "_client": client_name})

        if not to_confirm:
            return

        # 弹卡片让用户确认
        from ethan.browser.cleanup_confirm import TIMEOUT_SECONDS, await_confirm, create_confirm

        # 尝试获取 session 标题信息（用第一个 client 查询即可）
        try:
            first_client = to_confirm[0]["_client"]
            list_result = await hub.call(METHODS["session_list"], {}, client_name=first_client)
            sessions_info = {
                s.get("sessionId"): s for s in (list_result or {}).get("sessions", []) if isinstance(s, dict)
            }
            for item in to_confirm:
                info = sessions_info.get(item["sessionId"])
                if info:
                    item["title"] = info.get("title", "")
                    item["tabCount"] = info.get("tabCount", 0)
        except Exception:
            pass

        confirm_req = create_confirm(session_id, to_confirm)
        if run is not None:
            run.emit(
                {
                    "confirm_browser_cleanup": True,
                    "request_id": confirm_req.request_id,
                    "sessions": [
                        {"sessionId": s["sessionId"], "title": s["title"], "tabCount": s["tabCount"]}
                        for s in to_confirm
                    ],
                    "timeout": TIMEOUT_SECONDS,
                }
            )

        action = await await_confirm(confirm_req)

        # 根据用户选择执行
        for item in to_confirm:
            bsid = item["sessionId"]
            cname = item.get("_client", "")
            if not cname:
                # 没有客户端名就无法再路由到这个 session，留着也是死绑定
                smap.unbind(bsid)
                continue
            if action == "close":
                # 关闭：真正关掉 tab group，扩展侧也不再追踪 → 解绑是正确的
                try:
                    await hub.call(
                        METHODS["session_close"], {"sessionId": bsid}, client_name=cname, browser_session_id=bsid
                    )
                except Exception:
                    logger.warning("browser: cleanup close failed for %s", bsid)
                finally:
                    smap.unbind(bsid)
            else:
                # "keep"：用户要保留这些 tab，扩展继续追踪，**绑定也必须保留**。
                # 过去这里无条件 unbind，于是「保留」等于「后端失忆」——扩展还记着
                # session，ethan 却查不到了；下一轮 session_list 返回空，agent 判定
                # 没有可用 session 就去 attach/create，在多客户端下进一步触发
                # 「请先 use 选一个」，整个整理流程空转（实测多浏览器标签整理场景）。
                # 保留时也把 keep_alive 置上，避免下一轮收尾又把它当成待清理项弹卡片。
                # bind 会新建 _Entry（last_active 自动置为当前），无需再 touch。
                smap.bind(bsid, session_id, client_name=cname, keep_alive=True)
                logger.info("browser: kept session %s (client=%s) after cleanup", bsid, cname)
    except Exception:
        logger.debug("browser cleanup skipped: %s", session_id)
