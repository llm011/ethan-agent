r"""Android 对话区的「还在跑」提示 —— 不能因为有过工具调用就消失。

## 真实症状

用户原话：「我用 dsh 内核，我看到在跑的过程，app 对话区没有 loading 的样式，
看不出他还在跑。其他内核不知道是不是也是这样」。

## 根因

`ChatScreen` 里流式提示的显示条件原本是：

    message.isStreaming && message.content.isEmpty() && message.toolSteps.isEmpty()

`toolSteps.isEmpty()` 这一条是致命的：外部内核（DSH / Claude Code）的标准工作
模式是「调工具 → 想 → 再调」，**一旦发生过任何工具调用，`toolSteps` 就永久非空**，
这个提示再也不会出现。

与此同时 `ToolTimeline` 里的 spinner 只在有 step 处于 `running` 时才显示。
于是在「工具都跑完了、模型正在想下一步」这段最常见的等待期，屏幕上
**没有任何进行中动画** —— 看起来像卡死了。

这对所有内核都成立，只是 DSH 的工具调用最密集，最容易暴露。

## 契约

1. 流式提示不能以「工具步骤为空」为前提
2. 但也不能在没有流式时显示
3. 有工具步骤时代码要还在（措辞可以不同）
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/chat/ChatMessageBubble.kt"
COMMON = ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/components/Common.kt"


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _indicator_block() -> str:
    """截取流式提示那段代码（从 isStreaming 判断到 TypingDots 之后）。"""
    src = _src(CHAT)
    idx = src.find("message.isStreaming && message.content.isEmpty()")
    assert idx > 0, "找不到流式提示的判断"
    return src[idx : idx + 900]


def test_indicator_does_not_require_empty_tool_steps():
    """核心回归：条件里不能再有 `toolSteps.isEmpty()`。

    加上它就意味着「只要调过一次工具，提示永远不显示」。
    """
    block = _indicator_block()
    # 只看条件行（第一行），避免误伤注释里提到的历史写法
    first_line = block.split("\n", 1)[0]
    assert "toolSteps.isEmpty()" not in first_line, (
        "流式提示不能要求 toolSteps 为空 —— 外部内核调过工具后就永久非空，"
        "提示再也不会出现（实测 DSH 就是这样）"
    )


def test_indicator_requires_streaming():
    """不能无条件显示 —— 必须仍在流式中。"""
    block = _indicator_block()
    first_line = block.split("\n", 1)[0]
    assert "isStreaming" in first_line, "提示必须受 isStreaming 约束"


def test_indicator_requires_empty_content():
    """有正文时不显示动画 —— 那时光标/文案本身就是反馈。"""
    block = _indicator_block()
    first_line = block.split("\n", 1)[0]
    assert "content.isEmpty()" in first_line


def test_indicator_adapts_wording_when_tools_ran():
    """有工具步骤时应换措辞（继续处理中 / 思考中），而不是一律「思考中」。"""
    block = _indicator_block()
    assert "继续处理中" in block, "有工具步骤时应给更贴切的措辞"
    assert "思考中" in block


def test_typing_dots_still_rendered():
    """提示本体还在（TypingDots），不是把整段删了。"""
    block = _indicator_block()
    assert "TypingDots" in block


def test_web_does_not_have_the_same_bug():
    """Web 端的条件是 `isStreaming && isLast`，不含 toolSteps —— 本来就正常。

    这条是防止有人「统一三端」时把 Android 的坏条件搬到 Web。
    """
    web = (ROOT / "web/components/chat/message-bubble.tsx").read_text(encoding="utf-8")
    m = re.search(r"\{msg\.role === \"assistant\" && isStreaming && isLast && \(", web)
    assert m, "Web 端的流式提示条件不见了"
    # 该条件附近不应出现 toolSteps.isEmpty
    tail = web[m.start() : m.start() + 300]
    assert "toolSteps.isEmpty" not in tail, "Web 端不该加上 toolSteps 限制"


def test_tool_timeline_shows_spinner_while_running():
    """ToolTimeline 在有 running 步骤时要有 spinner —— 这是另一半反馈。"""
    src = _src(COMMON)
    assert "CircularProgressIndicator" in src
    assert "!allDone" in src, "spinner 应绑定在「有步骤未完成」上"
