"""已知 LLM provider 预设 —— `ethan provider set <key>` 一键配置时的默认值。

新增 provider 支持时,在 PROVIDER_PRESETS 加一条即可被 CLI 自动识别(无需新建 provider 类,
GLM 等第三方网关只要走 anthropic / openai_compat 协议就能复用现有实现)。

每条预设字段(均可被 CLI 旗标或 config.yaml 覆盖):
  base_url:            网关地址
  type:                "anthropic" | "openai_compat" —— 决定走哪个 provider 实现
  disable_prompt_cache: 第三方 Anthropic 兼容网关不支持 cache_control 时设 True
  description:         人类可读说明
  models:              常用 model id 列表,set 时自动注册(已存在则跳过)
  env_keys:            可填充该 provider api_key 的环境变量名(供 _apply_env_overrides 用)
"""
from __future__ import annotations

PROVIDER_PRESETS: dict[str, dict] = {
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/anthropic",
        "type": "anthropic",
        "disable_prompt_cache": True,
        "description": "智谱 GLM (BigModel,Anthropic 兼容协议)",
        "models": ["glm-5.2", "glm-4.6", "glm-4.5"],
        "env_keys": ["GLM_API_KEY", "ZHIPU_API_KEY"],
    },
}


def get_preset(key: str) -> dict | None:
    return PROVIDER_PRESETS.get(key)
