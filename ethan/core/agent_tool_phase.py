"""Transport-specific authorization and tool interaction (loop step four)."""
from ethan.core.tool_format import (
    _format_args,
    classify_tool,
    extract_entity_id,
    resolve_skill_category,
)
from ethan.providers.base import Message, ToolEvent


class StreamToolPhase:
    async def prepare(self, agent, calls, working, gen_ms):
        # --- 授权检查：执行前对工具做（1）渠道硬策略 + （2）consent 确认 ---
        import asyncio as _aio

        from ethan.core.consent import get_consent_provider

        allowed_calls = []
        for tc in calls:
            tool = agent._registry.get(tc.name)

            # [ask_user 拦截] 非危险操作的用户确认/选择，不进 executor，阻塞等回复
            # TODO(风险: ask_user 飞书/微信等非 Web 渠道静默失效):
            #   AskUserProvider 只实现了 Web 消费端（SSE yield AskUserEvent → 前端 POST 回传）。
            #   飞书/微信渠道没有渲染卡片 + POST 回传的消费端，Agent 会 await 20s 后超时走 default，
            #   用户在三方渠道端完全无感知。需要在非 Web 渠道用飞书交互卡片/微信公众号菜单替换。
            if tc.name == "ask_user":
                from ethan.core.ask_user import AskUserProvider

                args = tc.arguments or {}
                question = args.get("question", "")
                options = args.get("options") or []
                default = args.get("default", "")
                timeout = 20

                yield ToolEvent(
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                    args_summary=question,
                    state="start",
                    skill_category=resolve_skill_category(tc.name, tc.arguments),
                    gen_ms=gen_ms,
                )

                _ask_provider = AskUserProvider()
                _ask_event, _ask_fut = _ask_provider.create(question, options, default, timeout)
                yield _ask_event

                try:
                    # 后端比前端倒计时多留 5s 余量：用户在倒计时最后几秒点击时，
                    # POST 有网络延迟，若与前端倒计时同刻超时会导致用户选择被丢弃
                    _ask_result = await _aio.wait_for(_ask_fut, timeout=timeout + 5)
                except (_aio.CancelledError, _aio.TimeoutError):
                    _ask_result = default
                    _ask_provider.cancel_all()

                yield ToolEvent(
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                    args_summary=question,
                    state="done",
                    result_preview=f"用户选择：{_ask_result}",
                    skill_category=resolve_skill_category(tc.name, tc.arguments),
                )
                working.append(Message(role="tool", content=f"用户选择：{_ask_result}", tool_call_id=tc.id))
                continue

            # [wait_for_user 拦截] 等待用户完成外部操作（OAuth/浏览器操作等），不进 executor，长超时阻塞
            if tc.name == "wait_for_user":
                from ethan.core.wait_for_user import WaitForUserProvider

                args = tc.arguments or {}
                prompt = args.get("prompt", "")
                input_type = args.get("input_type", "confirm")
                placeholder = args.get("placeholder", "")
                confirm_label = args.get("confirm_label", "已完成")
                cancel_label = args.get("cancel_label", "取消")
                # 容错解析 timeout：LLM 可能传非数字（如 "abc" 或 "300s"），兜底 300s
                try:
                    timeout = min(int(args.get("timeout", 300)), 600)
                except (TypeError, ValueError):
                    timeout = 300

                yield ToolEvent(
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                    args_summary=prompt,
                    state="start",
                    skill_category=resolve_skill_category(tc.name, tc.arguments),
                    gen_ms=gen_ms,
                )

                _wfu_provider = WaitForUserProvider()
                _wfu_event, _wfu_fut = _wfu_provider.create(
                    prompt,
                    input_type,
                    placeholder,
                    confirm_label,
                    cancel_label,
                    timeout,
                )
                yield _wfu_event

                try:
                    # 后端比前端倒计时多留 5s 余量，避免用户最后时刻点击被超时丢弃
                    _wfu_result = await _aio.wait_for(_wfu_fut, timeout=timeout + 5)
                except _aio.CancelledError:
                    _wfu_provider.cancel_all()
                    raise
                except _aio.TimeoutError:
                    _wfu_result = "timeout"
                    _wfu_provider.cancel_all()

                if _wfu_result == "timeout":
                    _wfu_preview = "等待超时"
                elif _wfu_result == "cancel":
                    _wfu_preview = "用户取消"
                elif _wfu_result == "done":
                    _wfu_preview = "用户确认完成"
                else:
                    _wfu_preview = f"用户输入：{_wfu_result}"

                yield ToolEvent(
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                    args_summary=prompt,
                    state="done",
                    result_preview=_wfu_preview,
                    skill_category=resolve_skill_category(tc.name, tc.arguments),
                )
                working.append(Message(role="tool", content=_wfu_preview, tool_call_id=tc.id))
                continue

            consent_provider = get_consent_provider()

            # (1) 渠道硬策略：如三方渠道认主人后，非主人不得执行 side_effect 工具。
            #     直接拒绝，不询问（三方渠道无交互确认 UI）。
            if consent_provider is not None:
                side_effect = bool(getattr(tool, "side_effect", False)) if tool else False
                deny = consent_provider.policy_check(tc.name, side_effect)
                if deny:
                    # 静默拒绝：不 yield ToolEvent（不在 UI 展示报错），
                    # 只把拒绝原因回给模型让它调整回复。
                    working.append(Message(role="tool", content=deny, tool_call_id=tc.id))
                    continue

            # (2) consent 确认：工具自身声明需要授权时（如读密钥）走交互/拒绝流程。
            desc = tool.consent_check(**tc.arguments) if tool else None
            if desc:
                # session 维度授权记忆：按 consent_scope 粒度（工具名 或 目录路径）记忆，
                # 同会话内此 scope 已授权过则直接放行（目录授权后子目录免问）。
                # 但 consent_always=True 的高危调用（如 rm -rf）绕过记忆，每次都问、且不记入放行。
                from ethan.core.consent import AutoConsentProvider, is_granted, record_grant

                sess_id = getattr(consent_provider, "session_id", "") if consent_provider else ""
                scope = tool.consent_scope(**tc.arguments) if tool else tc.name
                always = tool.consent_always(**tc.arguments) if tool else False
                # 超级权限（auto_approve）模式只对「破坏性」调用保留强制弹窗
                # （rm -rf / 格式化 / 写设备等，见 consent_destructive）；
                # 其余高危（sudo / 管道执行 / env dump / secret 引用等）自动放行
                # ——用户开启超级权限即接管这部分风险，避免 curl 等日常命令
                # 被反复弹窗打断（2026-08-22 用户反馈）。
                # 注意：每次工具调用都重新读 auto_approve —— 用户可能在生成
                # 过程中才点开/关掉开关，必须立即生效（见 /api/chat/auto-consent）。
                if always and getattr(consent_provider, "auto_approve", False):
                    always = bool(tool.consent_destructive(**tc.arguments)) if tool else always
                if not always and is_granted(sess_id, scope):
                    allowed_calls.append(tc)
                    yield ToolEvent(
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        args_summary=_format_args(tc.arguments),
                        intent=str(tc.arguments.get("intent", "") or ""),
                        state="start",
                        entity_type=classify_tool(tc.name),
                        entity_id=extract_entity_id(tc.name, tc.arguments),
                        skill_category=resolve_skill_category(tc.name, tc.arguments),
                        gen_ms=gen_ms,
                    )
                    continue
                detail = _format_args(tc.arguments)
                ok = True
                consent_msg = ""  # 预初始化，避免 consent_provider is None 分支未赋值
                consent_timed_out = False
                consent_cancelled = False
                if consent_provider is None:
                    ok = True
                elif getattr(consent_provider, "auto_approve", False) and not always:
                    # 超级权限（web SuperConsentProvider）：非高危授权自动放行，不弹窗；
                    # 高危（always=True）仍走下方弹窗分支交还用户确认。
                    ok = True
                elif consent_provider.streamed:
                    # Web：向流注入 ConsentEvent，await 前端响应（加超时兜底，
                    # 避免用户一直不点导致 producer 永久挂起、run 不结束）
                    event, fut = consent_provider.create(desc, tc.name, detail, always=always)
                    yield event
                    try:
                        from ethan.core.consent import ConsentResult

                        result = await _aio.wait_for(fut, timeout=300)
                        if isinstance(result, ConsentResult):
                            ok = result.allowed
                            consent_msg = result.message
                        else:
                            ok = bool(result)
                            consent_msg = ""
                    except _aio.TimeoutError:
                        ok = False
                        consent_msg = ""
                        consent_timed_out = True
                        # 超时即摘除注册：fut 已被 wait_for 取消，但条目仍在
                        # _pending/_REGISTRY——迟到的「允许」会让前端误以为已批准
                        # （实际早已按拒绝处理），且条目要等到 cancel_all 才清
                        consent_provider.expire(event.request_id)
                    except _aio.CancelledError:
                        # 「停止生成」等外层取消：非用户拒绝，单独标记，
                        # 避免模型误以为用户表达过否定意见而停下来追问
                        ok = False
                        consent_msg = ""
                        consent_cancelled = True
                else:
                    ok = await consent_provider.request(desc, tc.name, detail, always=always)
                    consent_msg = ""
                if not ok:
                    # 拒绝来源区分：无人值守自动拒绝 / 等待超时 / 生成取消 ≠ 用户主动拒绝。
                    # 统一标「用户拒绝」会误导模型以为用户表达过否定意见而停下来追问。
                    if consent_cancelled:
                        reject_text = "[授权请求已取消（本次生成已停止），操作未执行]"
                        reject_preview = "已取消"
                    elif consent_timed_out:
                        reject_text = "[授权确认等待超时（5 分钟无响应），本次操作已按拒绝处理]"
                        reject_preview = "授权超时"
                    elif isinstance(consent_provider, AutoConsentProvider):
                        reject_text = (
                            "[自动授权模式下高危命令不会自动批准，本次已拒绝。"
                            "如确需执行，请在交互渠道（Web/桌面端）发起并在弹窗中确认，"
                            "或告知用户手动执行]"
                        )
                        reject_preview = "高危命令·自动拒绝"
                    else:
                        reject_text = "[用户拒绝此操作]"
                        reject_preview = "用户拒绝"
                    if consent_msg:
                        reject_text += f"\n用户补充说明：{consent_msg}"
                    yield ToolEvent(
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        args_summary=_format_args(tc.arguments),
                        intent=str(tc.arguments.get("intent", "") or ""),
                        state="start",
                        entity_type=classify_tool(tc.name),
                        entity_id=extract_entity_id(tc.name, tc.arguments),
                        skill_category=resolve_skill_category(tc.name, tc.arguments),
                        gen_ms=gen_ms,
                    )
                    yield ToolEvent(
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        args_summary="",
                        state="error",
                        result_preview=reject_preview,
                        skill_category=resolve_skill_category(tc.name, tc.arguments),
                    )
                    working.append(
                        Message(
                            role="tool",
                            content=reject_text,
                            tool_call_id=tc.id,
                        )
                    )
                    continue
                # 授权通过：如有用户补充信息，暂存待拼入 tool 结果（不插 user 消息，避免破坏 LLM 消息协议）
                if consent_msg:
                    if not hasattr(agent, "_consent_msgs"):
                        agent._consent_msgs = {}
                    agent._consent_msgs[tc.id] = consent_msg
                # 授权通过：记录到 session 维度（按 scope），后续同 scope 不再弹。
                # 高危调用（always）不记入放行，下次同类仍单独询问。
                if not always:
                    record_grant(sess_id, scope)
            allowed_calls.append(tc)
            yield ToolEvent(
                tool_name=tc.name,
                tool_call_id=tc.id,
                args_summary=_format_args(tc.arguments),
                intent=str(tc.arguments.get("intent", "") or ""),
                state="start",
                entity_type=classify_tool(tc.name),
                entity_id=extract_entity_id(tc.name, tc.arguments),
                skill_category=resolve_skill_category(tc.name, tc.arguments),
                gen_ms=gen_ms,
            )
        self.allowed_calls = allowed_calls
