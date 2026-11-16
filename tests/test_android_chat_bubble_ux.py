"""Android 对话气泡与执行过程折叠的交互契约。

覆盖三项交互约定：
1. 回复完成后，ToolTimeline 默认收起（流式中展开、结束后自动收起，历史消息默认收起；
   不跟踪 allDone 以免多轮工具调用期间闪烁）。
2. 气泡样式与侧边色条：Agent/工具气泡色条在左侧，用户 query 气泡色条在右侧，
   且气泡圆角按色条位置对称收窄（色条侧 6dp、对侧 18dp），用户气泡左侧留呼吸空间。
3. 用户问题过长时最多展示 5 行，超出时折叠并提供「查看全部 / 收起」。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/chat/ChatScreen.kt"
COMMON = ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/components/Common.kt"


def _chat_src() -> str:
    return CHAT.read_text(encoding="utf-8")


def _common_src() -> str:
    return COMMON.read_text(encoding="utf-8")


def test_tool_timeline_collapses_when_not_streaming():
    """ToolTimeline 初始状态跟随 isStreaming，回复完成后自动收起。"""
    src = _common_src()
    idx = src.find("fun ToolTimeline(")
    assert idx >= 0
    block = src[idx : idx + 2000]
    assert "mutableStateOf(isStreaming)" in block, "ToolTimeline 初始展开状态必须绑定 isStreaming（历史消息默认收起）"
    assert "mutableStateOf(true)" not in block, "不能写死默认展开 true"
    assert "LaunchedEffect(isStreaming)" in block, "需要在 isStreaming 结束时自动收起"
    assert "prevStreaming != isStreaming" in block, "只在 isStreaming 状态跳变时同步，避免多轮工具调用时闪烁"


def test_bubble_accent_bar_side_matches_role():
    """Agent 气泡边线在左，用户 query 气泡边线在右。"""
    src = _chat_src()
    assert "val barX = if (isUser) size.width - barWidth else 0f" in src
    assert "topLeft = Offset(barX, 0f)" in src


def test_bubble_corners_mirror_by_role():
    """带色条一侧使用 6dp 小圆角、对侧使用 18dp 柔和圆角，用户气泡左侧留白。"""
    src = _chat_src()
    assert "topStart = 18.dp, bottomStart = 18.dp, topEnd = 6.dp, bottomEnd = 6.dp" in src
    assert "topStart = 6.dp, bottomStart = 6.dp, topEnd = 18.dp, bottomEnd = 18.dp" in src
    assert "if (isUser) Modifier.padding(start = 32.dp) else Modifier" in src


def test_user_query_collapses_at_5_lines():
    """用户问题超过 5 行时折叠，最多展示 5 行并提供查看全部/收起。"""
    src = _chat_src()
    assert "private const val USER_QUERY_MAX_LINES = 5" in src
    assert "maxLines = if (userExpanded) Int.MAX_VALUE else USER_QUERY_MAX_LINES" in src
    assert "userOverflow = layoutResult.hasVisualOverflow" in src
    assert "fillMaxWidth = false" in src, "用户气泡里的展开/收起链接不能强行撑满整行宽度"
