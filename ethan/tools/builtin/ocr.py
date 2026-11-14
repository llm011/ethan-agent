"""OCR 工具 —— 从图片/PDF/Office 文档中提取文字。

## 定位：**兜底**，不是首选

模型自己就能读图（`ProviderConfig.vision` / `_supports_vision()`）。所以遇到图片时，
**正确顺序是先把图给模型看**，只有模型读不了、或者需要从 PDF/Office 里批量抽文字时，
才用这个工具。

这个先后顺序写进了工具描述里（`description`），因为模型选工具主要看描述——
如果只说「提取图片文字」，它会对每张图都调 OCR，既慢又费钱（OCR 按请求计费），
而模型自己看图是免费的、还能理解上下文。

真正不可替代的场景：
  · **PDF / Word / PPT**：模型无法直接把文档当图片读，必须抽取文本
  · 扫描件、截图里的密集文字（OCR 比模型逐字辨认更稳）
  · 需要**逐页保留版面结构**（`rich_layout_recognition`）

## 走 DeepSeek OCR API

`POST /v1/tools/ocr`，multipart 上传，两个 purpose：
  · `text_recognition` —— 不含图片的 Word/PPT 直接提取文字，其他逐页识别
  · `rich_layout_recognition` —— 所有文件逐页识别，输出带版面结构

## 为什么不做本地 OCR

本地方案（tesseract / paddleocr）要额外装一堆依赖和模型，而且中英混排与版面
还原质量明显不如这个云端服务。这个工具本来就是「兜底」，为此引入重依赖不划算。
"""
from __future__ import annotations

import logging
from pathlib import Path

from ethan.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# 官方限制（见 api-docs.deepseek.com/zh-cn/guides/ocr）
_MAX_BYTES = 100 * 1024 * 1024  # 100 MiB
_MAX_PAGES = 1000

# 支持的扩展名。注意官方是「按文件实际内容判断格式」，
# 这里列出来只用于「先给一个友好提示」，不用于拦截真实格式。
_SUPPORTED_EXT = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif",
}

# 纯图片扩展名：这些能用模型识图，所以会在描述里劝模型先自己看
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}


class OcrTool(BaseTool):
    fast_path = False
    cacheable = False  # 每次上传都产生费用，不该被缓存命中假装免费
    side_effect = True  # 会产生 API 费用

    name = "ocr_extract_text"
    description = (
        "从 PDF / Word / PPT / 图片中提取文字（DeepSeek OCR，按请求计费）。\n"
        "\n"
        "⚠️ 使用前先判断：如果只是**单张图片里的文字**，优先直接把图片交给模型看"
        "（模型自身支持读图，免费且能理解上下文），不要调本工具。\n"
        "\n"
        "本工具不可替代的场景：\n"
        "  · PDF / Word / PPT 等文档 —— 模型无法直接读，必须抽取文本\n"
        "  · 扫描件、密集排版文字 —— OCR 比逐字辨认更稳\n"
        "  · 需要保留版面结构的逐页识别（purpose='rich_layout_recognition'）\n"
        "\n"
        "限制：单文件 ≤ 100 MiB，≤ 1000 页。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要识别的文件路径（本地文件）。",
            },
            "purpose": {
                "type": "string",
                "enum": ["text_recognition", "rich_layout_recognition"],
                "description": (
                    "text_recognition（默认）：不含图片的 Word/PPT 直接提取文字，"
                    "其他文件逐页识别。"
                    "rich_layout_recognition：所有文件逐页识别，保留版面结构。"
                ),
                "default": "text_recognition",
            },
        },
        "required": ["path"],
    }
    # 识别结果是给模型读的正文，压成摘要会丢内容
    no_compress = True

    def consent_check(self, path: str = "", **kwargs) -> str | None:
        """上传用户文件到云端前必须授权。

        这是把**本地文件内容发给第三方**，与本地读文件的性质不同——
        用户有权知道这份文档会被上传。
        """
        return f"将文件上传到 DeepSeek OCR 识别（按请求计费）：{path}"

    async def run(self, path: str, purpose: str = "text_recognition") -> ToolResult:
        import httpx

        from ethan.core.config import load_config

        cfg = load_config().tools.web_fetch
        api_key = (cfg.api_key or "").strip()
        if not api_key:
            return ToolResult(
                tool_call_id="",
                content=(
                    "OCR 未配置：需要在 config.yaml 的 tools.web_fetch.api_key 里"
                    "填 DeepSeek API Key。\n"
                    "（也可以先用其他方式处理，比如模型直接读图片。）"
                ),
            )

        p = Path(path).expanduser()
        if not p.exists():
            return ToolResult(tool_call_id="", content=f"文件不存在：{path}")
        if not p.is_file():
            return ToolResult(tool_call_id="", content=f"不是文件：{path}")

        size = p.stat().st_size
        if size > _MAX_BYTES:
            return ToolResult(
                tool_call_id="",
                content=(
                    f"文件过大：{size / 1024 / 1024:.1f} MiB，"
                    f"超过上限 {_MAX_BYTES // 1024 // 1024} MiB。"
                ),
            )
        if size == 0:
            return ToolResult(tool_call_id="", content=f"文件为空：{path}")

        if purpose not in ("text_recognition", "rich_layout_recognition"):
            return ToolResult(
                tool_call_id="",
                content=f"未知 purpose：{purpose}（可选 text_recognition / rich_layout_recognition）",
            )

        base = (cfg.base_url or "https://api.deepseek.com").rstrip("/")
        proxy_url = None
        try:
            proxy_url = load_config().network.proxy or None
        except Exception:
            pass

        try:
            async with httpx.AsyncClient(
                timeout=180.0, proxy=proxy_url, trust_env=False
            ) as client:
                with p.open("rb") as fh:
                    resp = await client.post(
                        f"{base}/v1/tools/ocr",
                        headers={"Authorization": f"Bearer {api_key}"},
                        data={"purpose": purpose},
                        files={"file": (p.name, fh)},
                    )
        except httpx.TimeoutException:
            return ToolResult(tool_call_id="", content="OCR 超时（180s）。文件较大时可拆分后重试。")
        except Exception as e:  # noqa: BLE001 - 网络/文件错误统一给可读提示
            return ToolResult(tool_call_id="", content=f"OCR 失败：{e}")

        if resp.status_code == 413:
            return ToolResult(tool_call_id="", content="OCR 拒绝：文件超过 100 MiB（HTTP 413）。")
        if resp.status_code == 401:
            return ToolResult(tool_call_id="", content="OCR 鉴权失败（HTTP 401）：检查 API Key。")
        if resp.status_code == 402:
            return ToolResult(tool_call_id="", content="OCR 失败：账号余额不足（HTTP 402）。")
        if resp.status_code == 429:
            return ToolResult(
                tool_call_id="", content="OCR 被限流（HTTP 429）：稍等几秒后重试。"
            )
        if resp.status_code != 200:
            detail = ""
            try:
                detail = (resp.json().get("error") or {}).get("message", "")
            except Exception:
                detail = resp.text[:200]
            return ToolResult(
                tool_call_id="", content=f"OCR 失败（HTTP {resp.status_code}）：{detail}"
            )

        try:
            data = resp.json()
        except Exception:
            return ToolResult(tool_call_id="", content="OCR 返回了非 JSON 内容，无法解析。")

        text = self._extract_text(data)
        if not text:
            return ToolResult(
                tool_call_id="", content=f"OCR 未识别到文字（{p.name}）。可能是纯图片无文字内容。"
            )

        # 说明来源与代价，让模型知道要不要对多页文档继续调用
        header = f"[OCR {p.name}，purpose={purpose}]"
        if p.suffix.lower() in _IMAGE_EXT:
            header += "\n（提示：单张图片本可以直接交给模型看，OCR 是按请求计费的）"
        return ToolResult(tool_call_id="", content=f"{header}\n\n{text}")

    @staticmethod
    def _extract_text(data: dict) -> str:
        """从 OCR 响应里提取正文。

        官方响应结构在不同 purpose 下略有差异（一个是纯文本，一个是带版面结构），
        所以这里做宽容解析：优先找已知的顶层字段，再兜底遍历一层。
        """
        for key in ("text", "content", "markdown", "result"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

        # 逐页结构：pages: [{text/content/markdown...}]
        pages = data.get("pages")
        if isinstance(pages, list):
            parts: list[str] = []
            for i, page in enumerate(pages, 1):
                if not isinstance(page, dict):
                    continue
                for key in ("text", "content", "markdown"):
                    val = page.get(key)
                    if isinstance(val, str) and val.strip():
                        parts.append(f"--- 第 {i} 页 ---\n{val.strip()}")
                        break
            if parts:
                return "\n\n".join(parts)

        # 最后兜底：把顶层所有字符串字段按原样拼出来（不猜结构，但也不丢内容）
        loose = [
            f"{k}: {v}" for k, v in data.items()
            if isinstance(v, str) and v.strip()
        ]
        return "\n".join(loose)
