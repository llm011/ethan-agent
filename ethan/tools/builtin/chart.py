"""Chart Tool — 基于 quickchart.io 渲染图表，无需本地绘图库。

使用 Chart.js 语法描述图表，由 quickchart.io 服务端渲染为 PNG 并保存到本地。
无新依赖：只用 httpx（已有）。
"""
from __future__ import annotations

import json
import time

import httpx

from ethan.tools.base import BaseTool

_QUICKCHART = "https://quickchart.io/chart"


class ChartTool(BaseTool):
    fast_path = False
    name = "generate_chart"
    description = (
        "Generate a chart (line, bar, pie, etc.) and save it as a PNG image. "
        "Use for visualizing data: trends, comparisons, distributions. "
        "Returns the local file path — display it with the Read tool."
    )
    parameters = {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "description": "Chart type: 'line', 'bar', 'horizontalBar', 'pie', 'doughnut', 'radar'.",
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "X-axis labels (for line/bar) or category labels (for pie/doughnut).",
            },
            "datasets": {
                "type": "array",
                "description": "Array of dataset objects. Each: {label, data: number[], color?}",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "data": {"type": "array", "items": {"type": "number"}},
                        "color": {"type": "string", "description": "CSS color, e.g. 'rgb(59,130,246)'"},
                    },
                    "required": ["data"],
                },
            },
            "title": {
                "type": "string",
                "description": "Chart title shown at the top.",
            },
            "width": {
                "type": "integer",
                "description": "Image width in pixels (default: 700).",
                "default": 700,
            },
            "height": {
                "type": "integer",
                "description": "Image height in pixels (default: 350).",
                "default": 350,
            },
            "output_path": {
                "type": "string",
                "description": "File path to save the PNG (default: /tmp/chart_<timestamp>.png).",
            },
        },
        "required": ["chart_type", "labels", "datasets"],
    }

    # Default palette — cycles if more datasets than colors
    _PALETTE = [
        "rgb(59,130,246)",   # blue
        "rgb(16,185,129)",   # green
        "rgb(245,158,11)",   # amber
        "rgb(239,68,68)",    # red
        "rgb(139,92,246)",   # violet
        "rgb(20,184,166)",   # teal
    ]

    async def run(
        self,
        chart_type: str,
        labels: list,
        datasets: list,
        title: str = "",
        width: int = 700,
        height: int = 350,
        output_path: str = "",
    ) -> str:
        try:
            config = self._build_config(chart_type, labels, datasets, title)
            png = await self._render(config, width, height)
            path = output_path or f"/tmp/chart_{int(time.time())}.png"
            with open(path, "wb") as f:
                f.write(png)
            return f"Chart saved to {path} ({len(png):,} bytes). Use Read tool to display it."
        except httpx.HTTPStatusError as e:
            return f"Chart generation failed: HTTP {e.response.status_code} — {e.response.text[:200]}"
        except Exception as e:
            return f"Chart generation failed: {e}"

    def _build_config(self, chart_type: str, labels: list, datasets: list, title: str) -> dict:
        built_datasets = []
        for i, ds in enumerate(datasets):
            color = ds.get("color") or self._PALETTE[i % len(self._PALETTE)]
            alpha = color.replace("rgb(", "rgba(").replace(")", ", 0.15)") if "rgb(" in color else color

            entry: dict = {"data": ds["data"]}
            if ds.get("label"):
                entry["label"] = ds["label"]

            if chart_type in ("line",):
                entry.update({
                    "borderColor": color,
                    "backgroundColor": alpha,
                    "fill": len(datasets) == 1,  # fill only for single-dataset lines
                    "tension": 0.3,
                    "pointRadius": 4,
                    "pointHoverRadius": 6,
                })
            elif chart_type in ("bar", "horizontalBar"):
                entry["backgroundColor"] = color
            elif chart_type in ("pie", "doughnut"):
                # For pie/doughnut use palette for segments
                entry["backgroundColor"] = self._PALETTE[:len(ds["data"])]

            built_datasets.append(entry)

        cfg: dict = {
            "type": chart_type,
            "data": {"labels": [str(lbl) for lbl in labels], "datasets": built_datasets},
        }

        options: dict = {"plugins": {}, "scales": {}}
        if title:
            options["plugins"]["title"] = {"display": True, "text": title, "font": {"size": 14}}
        options["plugins"]["legend"] = {"display": len(datasets) > 1}

        if chart_type in ("line", "bar", "horizontalBar"):
            options["scales"] = {
                "x": {"ticks": {"maxRotation": 45}},
                "y": {"beginAtZero": False},
            }

        cfg["options"] = options
        return cfg

    async def _render(self, config: dict, width: int, height: int) -> bytes:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                _QUICKCHART,
                params={
                    "c": json.dumps(config, ensure_ascii=False),
                    "w": width,
                    "h": height,
                    "bkg": "white",
                    "f": "png",
                },
            )
            resp.raise_for_status()
        return resp.content
