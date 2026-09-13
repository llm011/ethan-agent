"""内联图片卡片去重：tool_steps 不得重复携带 base64 图片。

背景：file_read / image_search 的图片卡片一旦带 data URI，同一份数据会被
StreamCollector 同时写进 messages.cards 和 tool_steps，单条消息膨胀到数 MB，
前端点开会话要等好几秒。本测试锁住「tool_steps 只挂轻量卡片」这一约束。
"""
from ethan.core.stream_collector import StreamCollector, _card_has_inline_image
from ethan.providers.base import ToolEvent


def _start(name: str, call_id: str = "c1") -> ToolEvent:
    return ToolEvent(tool_name=name, args_summary="", state="start", tool_call_id=call_id)


def _done(name: str, call_id: str = "c1", cards=None) -> ToolEvent:
    return ToolEvent(tool_name=name, args_summary="", state="done",
                     tool_call_id=call_id, result_preview="ok", cards=cards)


class TestCardHasInlineImage:
    def test_data_uri_is_inline(self):
        assert _card_has_inline_image({"type": "image", "url": "data:image/png;base64,AAAA"})

    def test_asset_path_is_not_inline(self):
        assert not _card_has_inline_image(
            {"type": "image", "url": "assets/images/s_1/1690000000_0.png"}
        )

    def test_search_card_is_not_inline(self):
        assert not _card_has_inline_image(
            {"type": "search_result", "title": "x", "url": "https://example.com"}
        )

    def test_long_raw_base64_field_is_inline(self):
        assert _card_has_inline_image({"type": "image", "data": "A" * 5000})

    def test_short_data_field_is_not_inline(self):
        assert not _card_has_inline_image({"type": "image", "data": "abc"})

    def test_non_dict_is_not_inline(self):
        assert not _card_has_inline_image(None)
        assert not _card_has_inline_image("data:image/png;base64,AAAA")


class TestToolStepsDedupe:
    def test_inline_image_card_not_attached_to_step(self):
        """带 base64 的图片卡片只进 collector.cards，不进 tool_steps。"""
        c = StreamCollector()
        big = {"type": "image", "title": "a.png", "url": "data:image/png;base64," + "A" * 3000}
        c.feed(_start("file_read"))
        c.feed(_done("file_read", cards=[big]))

        # 消息级 cards 保留（前端从这里渲染）
        assert len(c.cards) == 1
        assert c.cards[0]["url"].startswith("data:image/png")
        # tool_steps 不重复挂
        assert c.tool_steps[0].get("cards", []) == []

    def test_light_card_still_attached_to_step(self):
        """web_search 的轻量卡片行为不变——前端时间线依赖 step.cards。"""
        c = StreamCollector()
        light = [{"type": "search_result", "title": "t", "url": "https://example.com"}]
        c.feed(_start("web_search"))
        c.feed(_done("web_search", cards=light))

        assert len(c.cards) == 1
        assert c.tool_steps[0]["cards"] == light

    def test_mixed_cards_keep_only_light_on_step(self):
        """混合卡片：step 只留轻量的，图片卡片仍完整保留在消息级。"""
        c = StreamCollector()
        heavy = {"type": "image", "url": "data:image/png;base64," + "A" * 3000}
        light = {"type": "search_result", "title": "t", "url": "https://example.com"}
        c.feed(_start("mixed_tool"))
        c.feed(_done("mixed_tool", cards=[heavy, light]))

        assert len(c.cards) == 2  # 消息级两条都在
        assert c.tool_steps[0]["cards"] == [light]  # step 只留轻量的

    def test_asset_path_image_card_still_attached(self):
        """落盘后的图片卡片（assets/images/...）体积很小，照常挂到 step。"""
        c = StreamCollector()
        card = {"type": "image", "url": "assets/images/s_1/1.png", "title": "a.png"}
        c.feed(_start("file_read"))
        c.feed(_done("file_read", cards=[card]))

        assert c.tool_steps[0]["cards"] == [card]
