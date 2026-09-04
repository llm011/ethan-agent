"""Tests for WorkingMemory.from_history / _split_keep_recent 的连续 user 消息处理。

回归背景（会话 s_20260903_1907_6195 实测坏例）：用户首条消息（含任务 URL + key）
后紧跟第二条 user（"重试下"），旧版按 (user, assistant) 严格配对时首条无法配对、
被静默丢弃，导致整场会话模型都看不到任务原文，只能靠 recall_memory 猜任务并被
长期记忆带偏（答非所问）。
"""
from __future__ import annotations

from ethan.memory.working import WorkingMemory
from ethan.providers.base import Message


def _u(text: str) -> Message:
    return Message(role="user", content=text)


def _a(text: str) -> Message:
    return Message(role="assistant", content=text)


class TestFromHistoryOrphanUser:
    def test_consecutive_users_not_dropped(self):
        """连续两条 user 后跟 assistant：首条任务原文必须保留。"""
        history = [
            _u("帮我测试这个API：https://x.cn/v1 sk-abc"),
            _u("重试下"),
            _a("[Error: Connection refused]"),
        ]
        hot = WorkingMemory.from_history(history).build_context()
        joined = "\n".join(m.content or "" for m in hot)
        assert "https://x.cn/v1" in joined
        assert "重试下" in joined

    def test_consecutive_users_merged_single_message(self):
        """合并后的热区保持 user/assistant 严格交替。"""
        history = [_u("任务A"), _u("补充B"), _a("收到"), _u("继续"), _a("好的")]
        hot = WorkingMemory.from_history(history).build_context()
        roles = [m.role for m in hot]
        assert roles == ["user", "assistant", "user", "assistant"]
        first_user = hot[0].content
        assert "任务A" in first_user and "补充B" in first_user

    def test_merge_concat_images(self):
        """合并轮里多条 user 的图片按序拼接。"""
        u1 = Message(role="user", content="图一", images=[{"data": "a", "media_type": "image/png"}])
        u2 = Message(role="user", content="图二", images=[{"data": "b", "media_type": "image/png"}])
        hot = WorkingMemory.from_history([u1, u2, _a("ok")]).build_context()
        assert len(hot) == 2
        assert [img["data"] for img in hot[0].images] == ["a", "b"]

    def test_trailing_unanswered_user_not_included(self):
        """尾部悬空 user 不进热区：调用方会单独 append 当前消息，避免重复。"""
        history = [_u("任务"), _a("结果"), _u("刚发出的这条")]
        hot = WorkingMemory.from_history(history).build_context()
        assert [m.content for m in hot] == ["任务", "结果"]

    def test_leading_assistant_kept_without_empty_user(self):
        """开头孤立 assistant 原样保留，且不注入空 user 消息。"""
        history = [_a("ack"), _u("问题"), _a("回答")]
        hot = WorkingMemory.from_history(history).build_context()
        assert hot[0].role == "assistant"
        assert hot[0].content == "ack"
        assert all(m.content for m in hot)

    def test_hot_size_limits_rounds_not_messages(self):
        """hot_size 按轮计：10 轮限制下多 user 轮不会被截丢内容。"""
        history = [_u("老任务"), _u("老补充"), _a("老回复")]
        history += [m for i in range(12) for m in (_u(f"q{i}"), _a(f"a{i}"))]
        hot = WorkingMemory.from_history(history, hot_size=10).build_context()
        joined = "\n".join(m.content or "" for m in hot)
        assert "老任务" not in joined  # 最老一轮溢出热区
        assert hot[-1].content == "a11"
        roles = [m.role for m in hot]
        # 严格交替：10 轮 = 20 条消息
        assert len(hot) == 20
        assert all(roles[i] == ("user" if i % 2 == 0 else "assistant") for i in range(20))

    def test_normal_alternating_unchanged(self):
        """常规交替历史行为不变。"""
        history = [_u("u1"), _a("a1"), _u("u2"), _a("a2")]
        hot = WorkingMemory.from_history(history).build_context()
        assert [m.content for m in hot] == ["u1", "a1", "u2", "a2"]


class TestSplitKeepRecentOrphanUser:
    def _split(self, messages, keep_pairs):
        from ethan.core.session_ops import _split_keep_recent
        return _split_keep_recent(messages, keep_pairs)

    def test_no_message_lost_with_consecutive_users(self):
        """所有消息都进「保留」或「待压缩」，无静默丢弃。"""
        history = [_u("任务原文"), _u("重试下"), _a("err"), _u("咋回事"), _a("没看到任务")]
        kept, to_compress = self._split(history, 1)
        all_kept = kept + to_compress
        assert {id(m) for m in all_kept} == {id(m) for m in history}
        assert [m.content for m in kept] == ["咋回事", "没看到任务"]
        assert [m.content for m in to_compress] == ["任务原文", "重试下", "err"]

    def test_trailing_user_goes_to_compress_not_kept(self):
        """尾部悬空 user 归入待压缩（会被摘要保留），不占保留名额。"""
        history = [_u("u1"), _a("a1"), _u("u2"), _a("a2"), _u("当前")]
        kept, to_compress = self._split(history, 1)
        assert [m.content for m in kept] == ["u2", "a2"]
        assert [m.content for m in to_compress] == ["u1", "a1", "当前"]

    def test_shorter_than_keep_pairs_keeps_all(self):
        history = [_u("u1"), _a("a1")]
        kept, to_compress = self._split(history, 3)
        assert [m.content for m in kept] == ["u1", "a1"]
        assert to_compress == []

    def test_no_complete_round_compresses_all(self):
        history = [_u("u1"), _u("u2")]
        kept, to_compress = self._split(history, 1)
        assert kept == []
        assert [m.content for m in to_compress] == ["u1", "u2"]
