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
import re as _re
from dataclasses import dataclass, field

# ── 阈值（经验值，必要时可上提到 config） ──────────────────────────
STUCK_WINDOW = 3          # 连续 N 轮同一签名 → 判定卡住
ERROR_WINDOW = 2          # 连续 N 轮同一签名且都报错 → 提前判定卡住（错误重试不必等满 3 轮）
MAX_REFLECTIONS = 2       # 最多反思几次；仍卡住则收尾放弃
TOOL_FREQ_LIMIT = 8       # 同一工具名连续调用超过此次数（参数也完全相同时） → 判定卡住
TOOL_FREQ_LIMIT_VARIED = 30  # 同一工具名连续调用但参数每次不同时的宽松阈值（如批量整理 tab）
_FREQ_LIMIT_EXEMPT = {"file_read", "rg_search", "fd_find", "skill_read"}
# shell 工具不整体豁免，而是按实际命令前缀判定（见 _effective_tool_name）

# 复合命令分隔符：只取最后一段（如 `cd /x && bytedcli tea` 应判为 bytedcli，而非 cd）
_CMD_SEP_RE = _re.compile(r"&&|\|\||[|;]")
# 前导环境变量赋值（FOO=bar）——跳过，取其后的真实命令
_ENV_ASSIGN_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# 前导包装命令（本身不代表操作意图）——跳过一层，取被包装的命令
_WRAPPER_CMDS = {"sudo", "env", "nohup", "time", "exec"}


def _effective_tool_name(tc) -> str:
    """提取工具的「有效名称」用于频率判定。

    对 shell 这类通用工具，只看工具名太粗暴（bytedcli tea vs bytedcli codebase 是完全不同的操作）。
    提取 command 参数中的一级命令 + 子命令作为有效名，例如：
      shell + "bytedcli tea ..." → "shell:bytedcli:tea"（取前两个 token）
      shell + "ls -la" → "shell:ls"（遇到 flag 即停）
      shell + "git status" → "shell:git:status"
      shell + "cd /x && bytedcli tea" → "shell:bytedcli:tea"（复合命令取最后一段）
      shell + "sudo env A=b bytedcli tea" → "shell:bytedcli:tea"（跳过包装/赋值前缀）
    """
    name = tc.name
    if name != "shell":
        return name
    cmd = tc.arguments.get("command", "") if isinstance(tc.arguments, dict) else ""
    if not cmd:
        return name
    # 复合命令只看最后一段（&& / || / | / ; 后的命令才是实际操作）
    segment = _CMD_SEP_RE.split(cmd)[-1].strip()
    if not segment:
        return name
    tokens = []
    for p in segment.split():
        if p.startswith("-") or p.startswith("'") or p.startswith('"'):
            break
        # 跳过前导环境变量赋值与包装命令，继续取真实命令
        if not tokens and (_ENV_ASSIGN_RE.match(p) or p in _WRAPPER_CMDS):
            continue
        tokens.append(p)
        if len(tokens) >= 2:
            break
    return f"shell:{':'.join(tokens)}" if tokens else name


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
    _freq_limit_varied: bool = False  # 最近一次 is_stuck 触发是否因为"同工具不同参数"达到宽松上限
    has_planned: bool = False  # 是否已调过 plan_write（用于决策提示里措辞调整）
    decision_count: int = 0  # 已注入决策提示的次数
    awaiting_decision_response: bool = False  # 决策提示已注入，下一轮需检测是否选 C

    def record(self, tool_calls, had_error: bool) -> None:
        self._signatures.append(_round_signature(tool_calls))
        self._errored.append(had_error)
        # 记录有效工具名（shell 按实际命令前缀区分，避免 bytedcli tea/codebase 被误判为重复）
        self._tool_names.append(_effective_tool_name(tool_calls[0]) if tool_calls else "")

    def is_stuck(self) -> bool:
        """是否陷入无效循环。三种触发：
        1. 连续 ERROR_WINDOW 轮同签名且都报错
        2. 连续 STUCK_WINDOW 轮同签名（精确重复）
        3. 同一工具名连续 TOOL_FREQ_LIMIT 轮且参数完全相同 → 严格卡住；
           参数不同 → 放宽到 TOOL_FREQ_LIMIT_VARIED 轮（varied）
        """
        self._freq_limit_varied = False
        sigs = self._signatures
        if len(sigs) >= ERROR_WINDOW:
            tail = sigs[-ERROR_WINDOW:]
            if len(set(tail)) == 1 and all(self._errored[-ERROR_WINDOW:]):
                return True
        if len(sigs) >= STUCK_WINDOW:
            tail = sigs[-STUCK_WINDOW:]
            if len(set(tail)) == 1:
                return True
        # 工具频率限制：同一工具名连续调用超过阈值（但豁免高频读写工具）
        if len(self._tool_names) >= TOOL_FREQ_LIMIT:
            tail = self._tool_names[-TOOL_FREQ_LIMIT:]
            if len(set(tail)) == 1 and tail[0] and tail[0] not in _FREQ_LIMIT_EXEMPT:
                # 进一步区分：参数是否也完全相同
                tail_sigs = sigs[-TOOL_FREQ_LIMIT:]
                if len(set(tail_sigs)) == 1:
                    # 参数完全相同 → 严格限制，立即判定卡住
                    return True
                # 参数不同 → 宽松模式，放宽到 TOOL_FREQ_LIMIT_VARIED
                if len(self._tool_names) >= TOOL_FREQ_LIMIT_VARIED:
                    long_tail = self._tool_names[-TOOL_FREQ_LIMIT_VARIED:]
                    if len(set(long_tail)) == 1:
                        self._freq_limit_varied = True
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
    """收尾轮追加到 system prompt 的指令。reason: 'stuck' | 'varied' | 'max_iters'。

    收尾轮禁用工具，让模型基于已有上下文生成收尾报告，而非截断。
    """
    if reason == "stuck":
        head = "你在当前任务上已尝试多种策略仍未突破，现在请停止尝试，把进展整理给用户。"
    elif reason == "varied":
        head = "你已经连续执行了很多步批量操作，先到这里吧。"
    else:
        head = "本轮执行的步数已经比较多了，先整理一下当前进展。"
    return (
        f"\n\n[System: {head}请用自然中文生成一段简洁收尾，包含："
        "①已完成什么（具体产出/发现）；"
        "②如果还没做完，剩余哪些工作；"
        "③建议用户看看当前效果，需要继续的话可以再告诉你。"
        "语气坦诚直接、轻松自然，不要道歉或套话，不要调用任何工具。]"
    )


# ── Adaptive Planning：决策提示 ─────────────────────────────────────
# 第 1 轮反应式执行（不打扰）。从第 2 轮起，每 3 轮在 working messages 末尾
# 追加一条 role=system 的决策提示，强制模型显式判断当前任务状态：
#   A) 即将完成 → 直接继续，简述下一步
#   B) 还有较多步骤 → 调 plan_write 列出后续步骤再执行
#   C) 需要更多信息 → 向用户提问
#
# 与之前软建议的差异：
#   1. 位置：working messages 末尾的 role=system（不是 system prompt suffix）
#   2. 时机：第 2 轮 + 之后每 3 轮（iter=1, 3, 6, 9, ...）
#   3. 形式：要求显式判断 + 一气呵成调工具（不是软建议可跳过）

# 触发轮次：iter 索引（从 0 开始）
#   iter=1（第 2 轮）：第一次触发
#   iter=3, 6, 9, ...：之后每 3 轮触发
_DECISION_FIRST_TRIGGER = 1  # 第 2 轮（iter=1）
_DECISION_INTERVAL = 3  # 之后每 3 轮触发一次


def should_trigger_decision(monitor: "LoopMonitor", iter_idx: int) -> bool:
    """是否应该在第 iter_idx 轮（0-based）触发决策提示。

    触发条件：
    1. iter_idx == 1（第 2 轮，已跑过 1 轮探路）
    2. iter_idx >= 3 且 iter_idx % 3 == 0（即 iter=3, 6, 9, ...）

    第 1 轮（iter=0）不触发：让模型先跑一步探路。
    """
    if iter_idx == _DECISION_FIRST_TRIGGER:
        return True
    if iter_idx >= 3 and iter_idx % _DECISION_INTERVAL == 0:
        return True
    return False


def decision_prompt_message(has_planned: bool = False) -> str:
    """决策提示消息内容（追加为 working messages 末尾的 role=system）。

    模型在同一个响应里既输出判断又调工具（不增加轮次）。

    A 门槛收紧到"最后 1 步"（不是 1-2 步），把中间状态赶到 B。
    B 提示加强：明确"2 步以上就选 B"，并给出 plan_write 的具体示例。
    """
    if has_planned:
        plan_hint = "按已有 plan 继续执行下一步即可"
    else:
        plan_hint = (
            "先调 plan_write(steps=[\"步骤1\", \"步骤2\", ...]) 列出剩余步骤，"
            "再继续执行第一步（plan_write 不占轮次，本轮即可继续）"
        )
    return (
        "[System 决策提示] 基于以上工具结果，判断当前任务状态并选择行动：\n"
        "  A) 最后 1 步收尾（本轮调完工具就能交付结果）→ 直接调工具，在 thought 里简述\n"
        f"  B) 还需 2 步以上（多个文件/多次同类操作/需要对比汇总）→ {plan_hint}\n"
        "  C) 需要更多信息或工具失败 → 调工具补全信息，或向用户提问\n"
        "判断原则：只要剩余工作不止 1 步，就选 B。先 plan 再执行能避免绕路和遗漏。\n"
        "请在 thought 里先输出「决策: X」标记（X 为 A/B/C），再发起对应的工具调用。]"
    )


# ── "需要更多信息"信号检测 + 增强上下文 ────────────────────────────
# 当模型在决策提示后选了 C（需要更多信息），下一轮追加：
#   1. 全量 skill 清单（含 frontmatter：name/description/trigger/category）
#   2. memory recall 扩到 30 条
# 这是有条件触发，不是每轮都带，避免 token 爆炸。

# 决策标记正则：匹配 "决策: A" / "决策：B" / "决策:C" 等（全角/半角冒号、大小写、空格都兼容）
# 优先从 thought 开头匹配（决策提示要求模型在 thought 里先输出「决策: X」）
_DECISION_PATTERN = _re.compile(r"决策\s*[:：]\s*([ABCabc])")


def parse_decision_choice(response_text: str) -> str | None:
    """从模型响应里解析决策标记，返回 'A'/'B'/'C' 或 None。

    优先匹配「决策: X」格式（决策提示明确要求的输出格式）。
    回退匹配「选 C」「选择C」「选项 C」等历史格式。
    """
    if not response_text:
        return None
    m = _DECISION_PATTERN.search(response_text)
    if m:
        return m.group(1).upper()
    # 回退：兼容模型未严格按格式输出但表达了选择
    text_lower = response_text.lower()
    fallbacks = [
        (["选 c", "选择c", "选项c", "决策: c", "决策： c", "决策:c", "决策：c"], "C"),
        (["选 b", "选择b", "选项b", "决策: b", "决策： b", "决策:b", "决策：b"], "B"),
        (["选 a", "选择a", "选项a", "决策: a", "决策： a", "决策:a", "决策：a"], "A"),
    ]
    for patterns, choice in fallbacks:
        if any(p in text_lower for p in patterns):
            return choice
    return None


def detect_need_more_info(response_text: str) -> bool:
    """检测模型是否在决策提示后选了 C（需要更多信息）。

    基于结构化标记解析（「决策: C」），而非关键词匹配——
    抗表达差异，不会因"无法判断""需要补充"等正常推理用词误触发。
    """
    return parse_decision_choice(response_text) == "C"


def enhanced_context_message(skills_brief: str = "", memory_recall_text: str = "", tools_brief: str = "") -> str:
    """增强上下文消息（模型主动要"更多信息"时注入到下一轮 working）。

    skills_brief: 全量 skill 简表（name + description + trigger + category）
    tools_brief: 全量工具简表（name + 一句话 desc，不含 schema）
    memory_recall_text: 扩大后的 memory recall 文本（30 条）

    体量控制：skill 简表 ~5-15KB + tool 简表 ~3-8KB + 30 memory ~6-12KB ≈ 4-9k tokens，
    能接受。完整 tool schema 不带，模型需要时调 find_tools 拉取。
    """
    parts = ["[System 增强上下文] 你在上一轮提到需要更多信息，已为你补充："]
    if skills_brief:
        parts.append(f"\n<all_skills_brief>\n{skills_brief}\n</all_skills_brief>")
    if tools_brief:
        parts.append(f"\n<all_tools_brief>\n[全量工具简表，需要 schema 时调 find_tools 激活]\n{tools_brief}\n</all_tools_brief>")
    if memory_recall_text:
        parts.append(f"\n<extended_memory>\n{memory_recall_text}\n</extended_memory>")
    parts.append(
        "\n请基于以上完整信息重新判断任务状态，选择 A/B/C 行动。"
    )
    return "".join(parts)
