"""上下文预算管控不得丢 tool 消息的 images（截图视觉通路）。

背景（真实 bug）：adb/browser 截图后 file_read 读图，图挂在 tool 消息的
images 上；同轮只要有一条 tool 输出超长触发 enforce_context_budget 的
截断/驱逐，_truncated_copy / _replace_content 重建 Message 时漏传 images
（dataclass 默认值 []），图被静默清空——而 content 里的说明文案还声称
「图片内容已附在本结果中」，模型下一轮就「读图失败」且无报错可查。
"""

from ethan.core.context_budget import (
    _replace_content,
    _truncated_copy,
    enforce_context_budget,
)
from ethan.providers.base import Message

_IMG = [{"data": "AAAA", "media_type": "image/png"}]


def test_truncated_copy_preserves_images():
    """单条超长截断：images 必须原样透传，不能被 dataclass 默认值清空。"""
    m = Message(role="tool", content="x" * 25000, tool_call_id="c1", images=list(_IMG))
    m2 = _truncated_copy(m, 20000)
    assert m2.content != m.content, "长内容应被截断"
    assert m2.images == _IMG, "截断后 images 必须保留（截图视觉通路）"


def test_replace_content_preserves_images():
    """web_fetch offload 等内容替换路径：images 同样必须透传。"""
    m = Message(role="tool", content="original", tool_call_id="c2", images=list(_IMG))
    m2 = _replace_content(m, "new content")
    assert m2.content == "new content"
    assert m2.images == _IMG, "替换 content 后 images 必须保留"


def test_budget_eviction_keeps_recent_screenshot_images():
    """多轮混合长输出的会话：最近 3 条 tool 消息（通常含最新截图）不被驱逐时图必须还在。"""
    msgs = [Message(role="user", content="截个图看看界面")]
    for i in range(6):
        msgs.append(Message(role="assistant", content="", tool_calls=[]))
        # 偶数轮是截图（content 短说明 + images），奇数轮是超长 shell 输出
        if i % 2 == 0:
            msgs.append(Message(role="tool", content="📷 已读取图片，内容已附上", tool_call_id=f"c{i}", images=list(_IMG)))
        else:
            msgs.append(Message(role="tool", content="r" * 18000, tool_call_id=f"c{i}"))
    enforce_context_budget(msgs)
    tool_msgs = [m for m in msgs if m.role == "tool"]
    for i, m in enumerate(tool_msgs):
        if i % 2 == 0:
            assert m.images == _IMG, f"第 {i} 条截图 tool 消息的 images 被预算管控清空了"


def test_budget_truncation_of_image_message_keeps_images():
    """截图 tool 消息自身超长被截断（极端场景）：images 也不能丢。"""
    msgs = [
        Message(role="user", content="go"),
        Message(role="assistant", content="", tool_calls=[]),
        Message(role="tool", content="x" * 25000, tool_call_id="c0", images=list(_IMG)),
        Message(role="user", content="继续"),
    ]
    enforce_context_budget(msgs)
    assert msgs[2].images == _IMG


def test_budget_eviction_drops_images_on_evicted_stub():
    """被驱逐压成 stub 的旧截图：图随折叠一并移除（省 token），文案注明，不让模型误以为还能看。

    注意：截图消息 content 须低于单条封顶（20000）——先被封顶就走了保图的截断路径，
    到不了驱逐。用 ~19000 字的截图 + 5 条 17000 字的消息把总量顶过 100000 预算，
    驱逐按长度降序会先淘汰截图这条。
    """
    msgs = [Message(role="user", content="go")]
    for i in range(6):
        msgs.append(Message(role="assistant", content="", tool_calls=[]))
        if i == 0:
            msgs.append(Message(role="tool", content="📷 图片内容已附上\n" + "x" * 18980, tool_call_id=f"c{i}", images=list(_IMG)))
        else:
            msgs.append(Message(role="tool", content="y" * 17000, tool_call_id=f"c{i}"))
    enforce_context_budget(msgs)
    stub = msgs[2]
    assert "已折叠" in stub.content, "旧截图消息应被驱逐压成 stub"
    assert stub.images == [], "被驱逐的旧截图应连图一起移除"
    assert "截图已随折叠一并移除" in stub.content, "文案必须注明图已移除"
