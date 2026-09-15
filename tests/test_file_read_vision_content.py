"""file_read 读图必须把图片内容附给模型（VLM 视觉通路）。

背景：agent 操作浏览器/CUA 截图后，常用 file_read 读截图文件「看看界面啥状态」。
此前 file_read 对图片只返回文字说明（"图片已在前端以卡片渲染"），模型自己看不到
内容，只能干瞪眼或反复换姿势重试。现把图片本体放进 ToolResult.images——

- 与 browser / computer_use 截图同一通路：anthropic 协议进 tool_result content
  数组，OpenAI 兼容层在 tool 消息后补 image_url user 消息；
- 非 VLM 模型由 agent 层 reactive strip / provider 层 supports_vision 兜底剥离；
- svg / bmp 不被 VLM API 接受，不附图（仍给前端卡片）；
- 附图前先 downscale_image_b64 缩放，控制上下文体积。

tool 消息不入库（sessions.db 只存 user/assistant），不会重蹈 #326 的 DB 膨胀。
"""
import asyncio
import base64
import io

from ethan.core import context as ctx
from ethan.tools.builtin.file import FileReadTool

try:
    from PIL import Image

    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

# 1x1 透明 PNG（无 Pillow 时兜底用）
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42m"
    "P8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
)


def _png_bytes(w=100, h=80) -> bytes:
    if not HAVE_PIL:
        return base64.b64decode(_PNG_B64)
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 30, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _read(path) -> object:
    token = ctx.ETHAN_SESSION_ID.set("sess_vision_test")
    try:
        return asyncio.run(FileReadTool().run(str(path)))
    finally:
        ctx.ETHAN_SESSION_ID.reset(token)


def test_png_result_attaches_vision_image(tmp_path):
    """读 png：ToolResult.images 必须带上合法 base64 图片，且卡片照常返回。"""
    p = tmp_path / "shot.png"
    p.write_bytes(_png_bytes())

    result = _read(p)

    assert result.images and len(result.images) == 1, "读图必须附视觉内容给模型"
    img = result.images[0]
    assert img["media_type"] == "image/png"
    base64.b64decode(img["data"])  # 必须是合法 base64
    assert "可直接查看分析" in result.content, "文字说明要告知模型图已附上"
    assert result.cards and result.cards[0]["type"] == "image", "前端卡片不受影响"


def test_svg_not_attached_as_vision(tmp_path):
    """svg 不被 VLM API 接受为 image block：只给卡片，不附图。"""
    p = tmp_path / "vec.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    result = _read(p)

    assert not result.images
    assert result.cards


def test_text_file_has_no_images(tmp_path):
    """普通文本文件不得附 images（视觉通路仅限图片）。"""
    p = tmp_path / "note.txt"
    p.write_text("hello")

    result = _read(p)

    # 文本文件返回 str，不走 ToolResult；无论如何不能带出 images
    if not isinstance(result, str):
        assert not result.images


def test_large_image_downscaled_to_max_dim(tmp_path):
    """超大图附给模型前必须缩放，控制上下文体积。"""
    p = tmp_path / "big.png"
    p.write_bytes(_png_bytes(3000, 2000))

    result = _read(p)

    assert result.images, "大图同样要附（缩放后）"
    img = Image.open(io.BytesIO(base64.b64decode(result.images[0]["data"])))
    assert max(img.size) <= 1568, f"附图应缩到 1568px 内，实际 {img.size}"
