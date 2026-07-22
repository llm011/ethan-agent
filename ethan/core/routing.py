import re
from dataclasses import dataclass

from ethan.core.config import get_config

# 强制走完整 Loop 的信号（不可配置，优先级最高）
_FORCE_FULL_SIGNALS = [
    "帮我写", "写一个", "写代码", "实现", "分析", "解释",
    "总结", "生成", "创建", "建立", "搭建",
    "重构", "优化代码", "调试", "debug", "修复",
    "review", "审查", "代码审查",
    "write", "implement", "analyze", "explain", "generate", "create",
    "refactor", "summarize",
]


# ---------------------------------------------------------------------------
# Instant Route: 极简问题零工具直答
# ---------------------------------------------------------------------------

# 纯算术表达式：数字 + 运算符 + 空格 + 括号
_MATH_EXPR_RE = re.compile(r'^[\d\s\+\-\*/\.\(\)\^%]+$')
# 必须包含至少一个运算符（纯数字如 "8080" 不应走 math 通道）
_MATH_HAS_OPERATOR_RE = re.compile(r'[\+\-\*/\^%]')
# 安全 eval 白名单（仅允许基本算术 AST 节点）
_SAFE_EVAL_NODES = {
    'Expression', 'BinOp', 'UnaryOp', 'Num', 'Constant',
    'Add', 'Sub', 'Mult', 'Div', 'Mod', 'Pow', 'FloorDiv',
    'USub', 'UAdd',
}
# 幂运算指数上限，防止 9^9999999999 卡死
_MAX_EXPONENT = 10000

_GREETING_EXACT = frozenset({
    "你好", "hello", "hi", "hey", "嗨", "早", "早上好", "上午好",
    "下午好", "晚上好", "晚安", "谢谢", "thanks", "thank you",
    "好的", "ok", "行", "明白", "了解", "收到", "继续", "嗯", "嗯嗯",
    "没事了", "算了", "再见", "拜拜", "bye",
})

# 末尾常见装饰性标点（匹配 greeting 前 strip 掉）
_TRAILING_PUNCTUATION_RE = re.compile(r'[!！~～.。,，…\s]+$')

# 时间类关键词
_TIME_KEYWORDS = frozenset({
    "现在几点", "几点了", "今天几号", "今天星期几", "什么时间",
    "当前时间", "现在时间", "now", "what time",
})


@dataclass
class InstantResult:
    """instant 路由预判结果。"""
    kind: str           # "math" | "time" | "greeting" | "direct"
    answer: str = ""    # math/time 类可直接给出答案；greeting/direct 由 LLM 裸答


def _safe_math_eval(expr: str) -> str | None:
    """安全地计算纯算术表达式。仅允许数字和基本运算符。"""
    import ast
    # ^ 在 Python 中是 XOR，用户通常意为幂运算
    normalized = expr.replace("^", "**").replace(" ", "")
    if not normalized:
        return None
    try:
        tree = ast.parse(normalized, mode='eval')
    except SyntaxError:
        return None
    # 白名单检查：只允许安全节点
    for node in ast.walk(tree):
        if type(node).__name__ not in _SAFE_EVAL_NODES:
            return None
    # 大数幂运算拦截：检查 ** 右侧是否超限
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            if isinstance(node.right, ast.Constant):
                exp_val = node.right.value
                if isinstance(exp_val, (int, float)) and abs(exp_val) > _MAX_EXPONENT:
                    return None
    try:
        result = eval(compile(tree, '<expr>', 'eval'), {"__builtins__": None}, {})
        # 格式化：整数不带小数点，浮点保留合理精度
        if isinstance(result, float) and result == int(result) and abs(result) < 1e15:
            return str(int(result))
        if isinstance(result, float):
            return f"{result:.10g}"
        return str(result)
    except (ZeroDivisionError, OverflowError, ValueError):
        return None


def classify_instant(text: str) -> InstantResult | None:
    """
    预判是否可以 instant 直答，跳过 tools / memory recall。

    返回 InstantResult 表示可以 short-circuit；None 表示走正常路由。
    优先级：
      1. FORCE_FULL 信号 → 不走 instant
      2. 已有 fast_rule 命中 → 不走 instant（交给专门工具处理）
      3. 纯数学表达式 → eval 直答
      4. 时间查询 → 系统时间直答
      5. 打招呼/确认 → LLM 裸答（无 tools、无 recall）
      6. 短文本无动作意图 → LLM 裸答
    """
    stripped = text.strip()
    lower = stripped.lower()

    # 有 FORCE_FULL 信号不走 instant
    if any(sig in lower for sig in _FORCE_FULL_SIGNALS):
        return None

    # 已有 fast_rule 命中（查天气、打车等需要工具的），不走 instant
    if _match_fast_rule(stripped) is not None:
        return None

    # 1) 纯算术表达式（必须包含运算符，排除纯数字如 "8080"）
    if (_MATH_EXPR_RE.match(stripped)
            and any(c.isdigit() for c in stripped)
            and _MATH_HAS_OPERATOR_RE.search(stripped)):
        answer = _safe_math_eval(stripped)
        if answer is not None:
            return InstantResult(kind="math", answer=answer)

    # 2) 时间查询
    if any(kw in lower for kw in _TIME_KEYWORDS):
        from datetime import datetime

        from ethan.core.timezone import get_local_timezone
        now = datetime.now(get_local_timezone())
        answer = now.strftime("%Y-%m-%d %H:%M:%S %A")
        return InstantResult(kind="time", answer=answer)

    # 3) 打招呼/确认（strip 末尾标点后精确匹配，兼容 "你好！" "谢谢~"）
    bare = _TRAILING_PUNCTUATION_RE.sub('', lower)
    if bare in _GREETING_EXACT:
        return InstantResult(kind="greeting")

    # 4) 短文本（<=20字）+ 无问号 + 无动作意图 → direct（保守策略）
    if len(stripped) <= 20:
        if "?" not in stripped and "？" not in stripped:
            return InstantResult(kind="direct")

    return None


# ---------------------------------------------------------------------------
# 原有路由逻辑
# ---------------------------------------------------------------------------


def _match_keyword(kw: str, text: str) -> bool:
    """关键词匹配，支持通配符 *。"""
    if "*" in kw:
        pattern = re.compile(kw.replace("*", ".*"))
        return bool(pattern.search(text))
    return kw in text


def _match_fast_rule(text: str, routing=None):
    """返回命中的 FastRule（按 fast_rules 顺序取第一条命中的），无命中返回 None。"""
    if routing is None:
        routing = get_config().defaults.routing
    for rule in routing.fast_rules:
        for kw in rule.keywords:
            if _match_keyword(kw, text):
                return rule
    return None


def _get_route(text: str, skill_triggers: list[str] | None = None) -> str:
    """
    返回路由档位：'fast' | 'full'

    规则（按优先级）：
    1. 有 FORCE_FULL 信号 → full（最高优先）
    2. 命中 fast_path Skill 的 trigger 关键词 → fast
    3. 命中任一 fast_rule 的关键字 → fast
    4. 其余 → full

    不再按字数分档——迭代上限统一为 defaults.max_tool_iterations。
    Fast Path 仅影响工具集和模型选择，不影响迭代次数。
    """
    lower = text.lower()

    if any(sig in lower for sig in _FORCE_FULL_SIGNALS):
        return "full"

    routing = get_config().defaults.routing

    if skill_triggers:
        for kw in skill_triggers:
            if _match_keyword(kw, text):
                return "fast"

    if _match_fast_rule(text, routing) is not None:
        return "fast"

    return "full"
