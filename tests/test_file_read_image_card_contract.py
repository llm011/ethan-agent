"""file_read 图片卡片契约：落盘后只带相对资产路径，不得内联 base64 / 本机路径。

回归背景（PR #326 深度 review 发现）：
file_read 落盘为资产文件后曾把 local_path 写成用户本机绝对路径 str(p)，
前端 getImageSrc() 优先吃 local_path → 拼成 /api/images/<basename> →
后端强制 img_ 前缀（只服务 image_search 的 /tmp/ethan_images）→ HTTP 400 破图。
本测试锁住产出卡片的结构，防止再退回破图状态。
"""
import asyncio
import base64

from ethan.core import context as ctx
from ethan.tools.builtin.file import FileReadTool

# 1x1 透明 PNG
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42m"
    "P8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
)


def _write_png(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(base64.b64decode(_PNG_B64))
    return p


def test_file_read_image_card_has_relative_url_and_empty_local_path(tmp_path):
    """
    不变量：
    - card.url 是相对资产路径（assets/images/...），不是 data URI
    - card.local_path 为空字符串（绝不能是本机绝对路径）
    """
    p = _write_png(tmp_path)
    sid = "sess_test_1"
    token = ctx.ETHAN_SESSION_ID.set(sid)
    try:
        result = asyncio.run(FileReadTool().run(str(p)))
    finally:
        ctx.ETHAN_SESSION_ID.reset(token)

    cards = getattr(result, "cards", None)
    assert cards, "file_read 读图应返回带 cards 的 ToolResult"
    card = cards[0]

    assert card["url"].startswith("assets/images/"), f"url 应为相对资产路径，实际 {card['url']!r}"
    assert not card["url"].startswith("data:"), "不得内联 base64"
    assert card.get("local_path", "") == "", f"local_path 必须为空，实际 {card.get('local_path')!r}"
    # 关键：本机绝对路径不得出现在卡片任何字段里
    assert str(p) not in card["url"]
    assert card.get("local_path") != str(p)


def test_file_read_image_asset_file_exists(tmp_path):
    """落盘的资产文件必须真实存在，url 指向它。"""
    from ethan.core.assets import image_file_path

    p = _write_png(tmp_path)
    sid = "sess_test_2"
    token = ctx.ETHAN_SESSION_ID.set(sid)
    try:
        result = asyncio.run(FileReadTool().run(str(p)))
    finally:
        ctx.ETHAN_SESSION_ID.reset(token)

    url = result.cards[0]["url"]
    rel = url[len("assets/images/"):]
    assert image_file_path(rel).is_file(), f"资产文件不存在: {rel}"
