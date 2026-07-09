"""Agent 主循环的「卡死检测 + 强制反思 + 优雅收尾」控制逻辑。

主循环原本是裸 ReAct（for _ in range(max_iters): 调模型 → 执行工具 → 回灌），
两个老问题：
  1. 模型原地打转（连续调同一工具同一参数）时不会自我纠正，一直绕到 max_iters；
  2. 跑满迭代直接吐死字符串 "[max tool iterations reached]"，用户不知道做了什么、卡在哪。

本模块提供三块（chat / stream_chat 共用，逻辑不重复）：
  - LoopMonitor：记录每轮工具调用签名，检测「卡住」（连续同签名 / 连续同错误）。
  - 反思注入：检测到卡住时，往上下文插一条强提醒，逼模型显式诊断并换路。
  - 收尾 prompt：放弃（反思耗尽）或跑满迭代时，禁用工具、让模型生成「已做/卡点/建议」收尾报告，
    而不是截断。

阈值取自工程经验（与扣子等公开实践一致）：窗口 3 轮、错误快速通道 2 轮、最多 2 次反思。
v1 的卡住判定按「工具名 + 参数精确签名」匹配——便宜且能覆盖绝大多数原地打转；
语义相似但不完全相同的重复（如搜索词换了大小写/空格）属已知漏判，后续可叠加相似度判定。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

# ── 阈值（经验值，必要时可上提到 config） ──────────────────────────
STUCK_WINDOW = 3          # 连续 N 轮同一签名 → 判定卡住
ERROR_WINDOW = 2          # 连续 N 轮同一签名且都报错 → 提前判定卡住（错误重试不必等满 3 轮）
MAX_REFLECTIONS = 2       # 最多反思几次；仍卡住则收尾放弃
TOOL_FREQ_LIMIT = 5       # 同一工具名连续调用超过此次数 → 判定卡住（即使参数不同）


def _round_signature(tool_calls) -> str:
    """一轮工具调用的稳定签名：按 (name, 参数 JSON) 排序后拼成字符串。

    参数全量进签名（含 offset/limit 等）——递增分页会产生不同签名，天然不被判为卡住；
    完全重复的调用才会签名一致。
    """
    parts = []
    for tc in tool_calls:
        try:
            args_key = json.dumps(tc.arguments, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            args_key = str(tc.arguments)
        parts.append(f"{tc.name}|{args_key}")
    return "\n".join(sorted(parts))


@dataclass
class LoopMonitor:
    """跟踪每轮工具调用，检测原地打转。"""

    _signatures: list[str] = field(default_factory=list)
    _errored: list[bool] = field(default_factory=list)
    _tool_names: list[str] = field(default_factory=list)  # 每轮主工具名（取第一个）
    reflections_used: int = 0
    awaiting_reflection_followup: bool = False  # 上一轮注入过反思，本轮需校验是否真换路
    _last_reflected_sig: str = ""

    def record(self, tool_calls, had_error: bool) -> None:
        self._signatures.append(_round_signature(tool_calls))
        self._errored.append(had_error)
        # 记录主工具名（取第一个调用的工具名）
        self._tool_names.append(tool_calls[0].name if tool_calls else "")

    def is_stuck(self) -> bool:
        """是否陷入无效循环。三种触发：
        1. 连续 STUCK_WINDOW 轮同签名（精确重复）
        2. 连续 ERROR_WINDOW 轮同签名且都报错
        3. 连续 TOOL_FREQ_LIMIT 轮使用同一工具（即使参数不同，搜同一主题换不同词也算）
        """
        sigs = self._signatures
        if len(sigs) >= ERROR_WINDOW:
            tail = sigs[-ERROR_WINDOW:]
            if len(set(tail)) == 1 and all(self._errored[-ERROR_WINDOW:]):
                return True
        if len(sigs) >= STUCK_WINDOW:
            tail = sigs[-STUCK_WINDOW:]
            if len(set(tail)) == 1:
                return True
        # 工具频率限制：同一工具名连续调用超过阈值
        if len(self._tool_names) >= TOOL_FREQ_LIMIT:
            tail = self._tool_names[-TOOL_FREQ_LIMIT:]
            if len(set(tail)) == 1 and tail[0]:
                return True
        return False

    def repeated_after_reflection(self) -> bool:
        """反思后这一轮是否又重复了反思前的签名（说明没听劝）。"""
        if not self._last_reflected_sig or not self._signatures:
            return False
        return self._signatures[-1] == self._last_reflected_sig

    def mark_reflected(self) -> None:
        self.reflections_used += 1
        self.awaiting_reflection_followup = True
        self._last_reflected_sig = self._signatures[-1] if self._signatures else ""

    def exhausted(self) -> bool:
        return self.reflections_used >= MAX_REFLECTIONS

    def last_signature_summary(self, max_chars: int = 200) -> str:
        if not self._signatures:
            return ""
        s = self._signatures[-1]
        return s[:max_chars] + ("…" if len(s) > max_chars else "")


# ── 注入文本 ──────────────────────────────────────────────────────

def reflection_message(monitor: LoopMonitor, last_result: str = "") -> str:
    """卡住时注入的强制反思提示（作为一条 system 消息插入下一轮上下文最前）。"""
    result_hint = f"\n- 最近一次工具返回（节选）：{last_result[:200]}" if last_result else ""
    return (
        "⚠️ 执行停滞警告 ⚠️\n"
        f"你已经连续若干轮执行了几乎相同的操作但没有取得进展：\n"
        f"- 重复的调用签名：{monitor.last_signature_summary()}{result_hint}\n"
        "这表明你可能在无效循环中。请在继续前先完成**强制自我诊断**"
        "（用 <diagnosis> 标签包裹，不超过 150 字）：\n"
        "1. 我在尝试解决什么子问题？\n"
        "2. 为什么这个方法反复没有进展？（说根本原因，不要写「参数有误」这种表面话）\n"
        "3. 还有哪些没试过的路径？（至少列 2 个不同方案）\n"
        "4. 接下来选哪条、为什么？\n"
        "诊断后**必须采取与之前本质不同的策略**：换工具 / 换根本思路（不是微调参数）/ "
        "信息已够就直接推进 / 缺权限或信息就明确告诉用户卡点并请求输入。\n"
        "禁止：用同样的工具和相似参数再试一次。"
    )


def reflection_followup_message() -> str:
    """反思后仍重复同一操作时的二次强提醒。"""
    return (
        "你刚才的操作与停滞前本质相同，没有采纳自己诊断里提出的替代方案。"
        "请立刻换一个真正不同的策略——换工具、换思路，或如果信息已够就直接给结论、"
        "缺信息就转而询问用户。不要再重复同样的调用。"
    )


def finalize_system_suffix(reason: str) -> str:
    """收尾轮追加到 system prompt 的指令。reason: 'stuck' | 'max_iters'。

    收尾轮禁用工具，让模型基于已有上下文生成「已做 / 卡点 / 建议」报告，而非截断。
    """
    if reason == "stuck":
        head = "你在当前任务上已尝试多种策略仍未突破，现在请停止尝试，把进展整理给用户。"
    else:
        head = "已接近最大执行步数限制，这是最后一次输出机会，不能再调用工具，请基于已有信息收尾。"
    return (
        f"\n\n[System: {head}请用自然中文生成一段简洁收尾，包含："
        "①已完成什么（具体产出/发现，有文件就给路径）；"
        "②卡在哪一步、具体什么问题（要具体，如「缺 X 权限」「Y 返回 404」，不要写「遇到困难」）；"
        "③要继续推进需要用户提供什么（明确具体）。语气坦诚直接，不要道歉或套话，不要调用任何工具。]"
    )
