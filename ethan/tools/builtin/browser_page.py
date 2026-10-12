"""Browser page implementation; browser.py keeps compatibility exports."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ethan.browser.hub import BrowserError

from .browser_compat import browser as B
from .browser_runtime import _BrowserToolBase


class BrowserPageTool(_BrowserToolBase):
    name = "browser_page"
    description = (
        "操作 session 的 active tab。snapshot 取页面 AX 树+ref(默认 interactive+compact),"
        "完整内容落盘/tmp,prompt 只带首段 10000 字,has_more=true 时用 snapshot_read 翻页;"
        "click/fill/type/press/hover/select/scroll_into_view 用 ref 交互;"
        "click_selector/fill_selector/hover_selector 用 CSS/XPath/text 直接定位(不依赖 snapshot,CDP mouse 真实点击);"
        "wait_for_element 等元素出现;scroll_to_text 按文本滚动;extract_content 提取内容;markdown 提取正文为干净 Markdown;"
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
                "input_enter", "scroll_find", "click_vlm", "markdown",
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
        # 提前拦缺参:snapshot_read 是读本地落盘文件,不需要 session;其余都要。
        # 缺参时给出可取 id 的下一步,而不是让它落到归属校验里报「不属于当前对话」。
        if action != "snapshot_read" and not session:
            return self._missing_session(action)
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
            result = await B._call("page_snapshot", params, browser_session_id=session)
            if not isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False)
            # 完整 snapshot 文本落盘，prompt 只带首段
            full_snapshot = result.get("snapshot", "")
            snap_path = B._persist_snapshot(full_snapshot, session)
            total = len(full_snapshot)
            chunk, chunk_len = B._chunk_text(full_snapshot, 0, B._SNAPSHOT_CHUNK_CHARS)
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
            length = int(kw.get("length", B._SNAPSHOT_CHUNK_CHARS))
            try:
                content = Path(path).read_text(encoding="utf-8")
            except (OSError, FileNotFoundError) as e:
                return json.dumps({"error": f"读取 snapshot 文件失败: {e}"}, ensure_ascii=False)
            total = len(content)
            chunk, chunk_len = B._chunk_text(content, offset, length)
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
            return json.dumps(await B._call("page_click", {"sessionId": session, "ref": kw.get("ref")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "fill":
            return json.dumps(await B._call("page_fill", {"sessionId": session, "ref": kw.get("ref"), "text": kw.get("text", "")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "type":
            return json.dumps(await B._call("page_type", {"sessionId": session, "ref": kw.get("ref"), "text": kw.get("text", "")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "press":
            return json.dumps(await B._call("page_press", {"sessionId": session, "key": kw.get("key")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "hover":
            return json.dumps(await B._call("page_hover", {"sessionId": session, "ref": kw.get("ref")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "select":
            return json.dumps(await B._call("page_select", {"sessionId": session, "ref": kw.get("ref"), "value": kw.get("value")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "scroll_into_view":
            return json.dumps(await B._call("page_scroll_into_view", {"sessionId": session, "ref": kw.get("ref")},
                                          browser_session_id=session), ensure_ascii=False)
        if action == "scroll":
            params = {"sessionId": session, "direction": kw.get("direction", "down")}
            if kw.get("pixels") is not None:
                params["pixels"] = kw["pixels"]
            return json.dumps(await B._call("page_scroll", params, browser_session_id=session), ensure_ascii=False)
        if action == "get":
            params = {"sessionId": session, "what": kw.get("what")}
            if kw.get("ref"):
                params["ref"] = kw["ref"]
            return json.dumps(await B._call("page_get", params, browser_session_id=session), ensure_ascii=False)
        if action == "mouse":
            params = {"sessionId": session, "action": kw.get("mouse_action", "move")}
            for k in ("x", "y", "delta_x", "delta_y"):
                if kw.get(k) is not None:
                    params[{"delta_x": "deltaX", "delta_y": "deltaY"}.get(k, k)] = kw[k]
            return json.dumps(await B._call("page_mouse", params, browser_session_id=session), ensure_ascii=False)
        if action == "wait":
            params = {"sessionId": session}
            if kw.get("ms") is not None:
                params["ms"] = kw["ms"]
            if kw.get("load"):
                params["load"] = kw["load"]
            return json.dumps(await B._call("page_wait", params, browser_session_id=session), ensure_ascii=False)
        if action == "screenshot":
            from ethan.browser.screenshot import save_screenshot
            result = await B._call("page_screenshot", {"sessionId": session}, browser_session_id=session)
            return await save_screenshot(result)
        if action == "upload":
            return json.dumps(await B._call(
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
            result = await B._call("page_save_pdf", params, browser_session_id=session)
            return json.dumps({**(result or {}), "path": out_path}, ensure_ascii=False)
        if action == "eval":
            result = await B._call("page_eval", {"sessionId": session, "script": kw.get("script", "")},
                                 browser_session_id=session)
            # 大 eval 结果（整页卡片列表等）落盘 + 截断首段，避免逐轮回灌撑爆上下文
            return B._truncate_eval_result(result, session)
        # ── selector 操作（不依赖 snapshot，直接用 CSS/XPath/text 定位 + CDP mouse 点击）──
        if action == "click_selector":
            script = B._build_locate_script(kw.get("selector", ""), kw.get("xpath", ""),
                                          kw.get("text", ""), int(kw.get("nth", 0)))
            raw = await B._eval_js(session, script)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not info.get("found"):
                return json.dumps({"ok": False, "error": "未找到匹配元素",
                                   "match_count": info.get("match_count", 0)}, ensure_ascii=False)
            await B._click_point(session, info["x"], info["y"])
            return json.dumps({"ok": True, "method": "selector/xpath/text",
                               "coords": {"x": info["x"], "y": info["y"]},
                               "text": info.get("text", "")}, ensure_ascii=False)
        if action == "fill_selector":
            import json as _json
            sel = kw.get("selector", "")
            xp = kw.get("xpath", "")
            txt = kw.get("text", "")
            locate = B._build_locate_script(sel, xp, "", 0)
            raw = await B._eval_js(session, locate)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not info.get("found"):
                return json.dumps({"ok": False, "error": "未找到匹配输入框"}, ensure_ascii=False)
            # 动态构造 target 表达式：sel 有值用 querySelector，否则用 xpath。
            # 不能写死 `querySelector(sel) || evaluate(xp)` —— sel 为空时 querySelector("")
            # 会抛 DOMException，|| 无法短路，xpath 兜底失效。
            if sel:
                target_expr = f"document.querySelector({_json.dumps(sel)})"
            elif xp:
                target_expr = f"document.evaluate({_json.dumps(xp)}, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue"
            else:
                target_expr = "document.activeElement"
            # 聚焦 + 清空 + 设值 + 触发 input/change 事件（兼容 React）
            fill_script = f"(() => {{\n  const el = {target_expr};\n  if (!el) return false;\n  el.focus();\n  el.value = {_json.dumps(txt)};\n  el.dispatchEvent(new Event('input', {{bubbles: true}}));\n  el.dispatchEvent(new Event('change', {{bubbles: true}}));\n  return true;\n}})()"
            await B._eval_js(session, fill_script)
            return json.dumps({"ok": True, "text": txt}, ensure_ascii=False)
        if action == "hover_selector":
            script = B._build_locate_script(kw.get("selector", ""), kw.get("xpath", ""),
                                          kw.get("text", ""), int(kw.get("nth", 0)))
            raw = await B._eval_js(session, script)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not info.get("found"):
                return json.dumps({"ok": False, "error": "未找到匹配元素"}, ensure_ascii=False)
            await B._call("page_mouse", {"sessionId": session, "action": "move",
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
                raw = await B._eval_js(session, check_script)
                if raw is True or raw == "true":
                    return json.dumps({"ok": True, "found": True, "selector": sel},
                                      ensure_ascii=False)
                await asyncio.sleep(0.3)
            return json.dumps({"ok": False, "found": False, "selector": sel,
                               "timeout_ms": timeout}, ensure_ascii=False)
        if action == "scroll_to_text":
            import json as _json
            txt = kw.get("text", "")
            script = f"(() => {{\n  const found = window.find({_json.dumps(txt)}, false, false, true, false, false, false);\n  if (!found) return JSON.stringify({{found: false}});\n  const sel = window.getSelection();\n  if (sel.rangeCount > 0) {{\n    const range = sel.getRangeAt(0);\n    range.startContainer.parentElement?.scrollIntoView({{block: 'center'}});\n    const r = range.getBoundingClientRect();\n    return JSON.stringify({{found: true, x: r.x + r.width/2, y: r.y + r.height/2}});\n  }}\n  return JSON.stringify({{found: false}});\n}})()"
            raw = await B._eval_js(session, script)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            return json.dumps(info, ensure_ascii=False)
        if action == "extract_content":
            import json as _json
            # or "body"：kw.get("selector", "body") 在传入空串时返回空串而非默认值，
            # 导致 querySelector("") 抛 DOMException，|| document.body 兜底失效。
            sel = kw.get("selector") or "body"
            strip_links = kw.get("strip_links", False)
            script = f"(() => {{\n  const el = document.querySelector({_json.dumps(sel)}) || document.body;\n  let text = el.innerText || '';\n  {(_json.dumps(strip_links) if strip_links else 'false')} && el.querySelectorAll('a').forEach(a => {{\n    // keep text, strip href\n  }});\n  return JSON.stringify({{text: text, length: text.length, selector: {_json.dumps(sel)}}});\n}})()"
            raw = await B._eval_js(session, script)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            # 内容太长时截断并提示
            max_len = 20000
            if info.get("length", 0) > max_len:
                info["truncated"] = True
                info["text"] = info["text"][:max_len]
                info["_hint"] = f"内容已截断（共 {info['length']} 字，前 {max_len} 字）。"
            return json.dumps(info, ensure_ascii=False)
        if action == "markdown":
            raw = await B._eval_js(session, B._MARKDOWN_SCRIPT)
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            # 内容太长时截断
            max_len = 30000
            if info.get("length", 0) > max_len:
                info["truncated"] = True
                info["markdown"] = info["markdown"][:max_len]
                info["_hint"] = f"内容已截断（共 {info['length']} 字，前 {max_len} 字）。"
            return json.dumps(info, ensure_ascii=False)
        if action == "find_elements":
            import json as _json
            sel = kw.get("selector", "")
            script = f"(() => {{\n  const els = document.querySelectorAll({_json.dumps(sel)});\n  const results = [];\n  for (let i = 0; i < Math.min(els.length, 50); i++) {{\n    const r = els[i].getBoundingClientRect();\n    results.push({{\n      index: i,\n      tag: els[i].tagName.toLowerCase(),\n      text: (els[i].innerText || '').slice(0, 60),\n      x: Math.round(r.x + r.width/2),\n      y: Math.round(r.y + r.height/2),\n    }});\n  }}\n  return JSON.stringify({{count: els.length, elements: results}});\n}})()"
            raw = await B._eval_js(session, script)
            return raw if isinstance(raw, str) else json.dumps(raw or {}, ensure_ascii=False)
        if action == "find_attributes":
            import json as _json
            sel = kw.get("selector", "")
            attrs = kw.get("attributes", [])
            attrs_js = _json.dumps(attrs)
            script = f'(() => {{\n  const el = document.querySelector({_json.dumps(sel)});\n  if (!el) return JSON.stringify({{found: false}});\n  const attrs = {attrs_js};\n  const result = {{}};\n  attrs.forEach(a => {{ result[a] = el.getAttribute(a); }});\n  return JSON.stringify({{found: true, attributes: result}});\n}})()'
            raw = await B._eval_js(session, script)
            return raw if isinstance(raw, str) else json.dumps(raw or {}, ensure_ascii=False)
        if action == "check_exist":
            import json as _json
            sel = kw.get("selector", "")
            script = f"JSON.stringify({{exist: !!document.querySelector({_json.dumps(sel)})}})"
            raw = await B._eval_js(session, script)
            return raw if isinstance(raw, str) else json.dumps(raw or {}, ensure_ascii=False)
        if action == "input_enter":
            import json as _json
            sel = kw.get("selector", "")
            txt = kw.get("text", "")
            fill_script = f"(() => {{\n  const el = document.querySelector({_json.dumps(sel)});\n  if (!el) return false;\n  el.focus();\n  el.value = {_json.dumps(txt)};\n  el.dispatchEvent(new Event('input', {{bubbles: true}}));\n  el.dispatchEvent(new Event('change', {{bubbles: true}}));\n  el.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}}));\n  return true;\n}})()"
            fill_result = await B._eval_js(session, fill_script)
            # fill_script 返回 false 表示元素未找到；丢弃返回值会导致即使填充失败
            # 仍无条件 press Enter 并报告 ok=True，误导模型。
            if fill_result is False or fill_result == "false":
                return json.dumps({"ok": False, "error": "未找到匹配元素", "selector": sel},
                                  ensure_ascii=False)
            # 也用 CDP press Enter 确保触发
            await B._call("page_press", {"sessionId": session, "key": "Enter"},
                        browser_session_id=session)
            return json.dumps({"ok": True, "text": txt, "selector": sel},
                              ensure_ascii=False)
        if action == "scroll_find":
            import json as _json
            sel = kw.get("selector", "")
            scroll_times = int(kw.get("scroll_times", 3))
            for i in range(scroll_times):
                check = f"JSON.stringify({{found: !!document.querySelector({_json.dumps(sel)}), count: document.querySelectorAll({_json.dumps(sel)}).length}})"
                raw = await B._eval_js(session, check)
                info = json.loads(raw) if isinstance(raw, str) else (raw or {})
                if info.get("found"):
                    return json.dumps({"ok": True, "found": True, "count": info.get("count", 1),
                                       "scrolls": i, "selector": sel}, ensure_ascii=False)
                await B._call("page_scroll", {"sessionId": session, "direction": "down", "pixels": 500},
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
        result = await B._call("page_screenshot", {"sessionId": session},
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
            f'在截图中找到"{prompt}"元素。返回其中心点坐标（相对于视口左上角，CSS像素）。只返回JSON，不要其他文字：{{"x": 数字, "y": 数字, "found": true/false, "reason": "简短说明"}}'
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
        await B._click_point(session, x, y)
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
        hint = B._HINTS.get(action, "")
        step = None
        if action in B._STEP_ACTIONS and session:
            step = B.get_session_map().increment_step(session)
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


