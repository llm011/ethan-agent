#!/bin/sh
# SearXNG entrypoint wrapper
#
# 根据环境变量 SEARXNG_PROXY_URL 动态切换代理 / 直连模式：
#   - 未设置 / 空  → 直连模式（settings.yml 原样使用，禁用国外引擎）
#   - 设置为代理 URL → 代理模式（注入 proxies，并放开大部分国外引擎）
#
# settings.yml 以只读方式挂载为 settings.template.yml，每次启动复制一份
# 可写副本，保证配置干净、幂等。
#
# 用法（docker-compose）:
#   environment:
#     - SEARXNG_PROXY_URL=http://host.docker.internal:7890
#   # 不用代理时留空或不设置即可
set -e

TEMPLATE="/etc/searxng/settings.template.yml"
TARGET="/etc/searxng/settings.yml"

# 从模板复制可写副本（每次启动重新生成，保证幂等）
if [ -f "$TEMPLATE" ]; then
    cp "$TEMPLATE" "$TARGET"
else
    echo "[entrypoint-wrapper] WARN: 模板 $TEMPLATE 不存在，跳过复制"
fi

# 根据环境变量决定模式
if [ -n "${SEARXNG_PROXY_URL:-}" ]; then
    echo "[entrypoint-wrapper] 代理模式: $SEARXNG_PROXY_URL"
    /usr/local/searxng/.venv/bin/python3 - "$TARGET" "$SEARXNG_PROXY_URL" <<'PYEOF'
import sys, yaml
path, proxy_url = sys.argv[1], sys.argv[2]
with open(path) as f:
    cfg = yaml.safe_load(f)

# 1. 注入出站代理
cfg.setdefault('outgoing', {})['proxies'] = {
    'http': [proxy_url],
    'https': [proxy_url],
}

# 2. 代理模式下也必须禁用的引擎（即使走代理也 init 失败或被反爬）
#    - wikidata/ahmia/torch: init 必然失败
#    - brave 全系列: 反爬严格，代理也返回 403/captcha
#    - vimeo: access denied
#    - google news: region 限制
#    - baidu: 对服务器 IP 100% CAPTCHA 拦截
#    - duckduckgo: cn-zh region 触发 CAPTCHA（SearXNG default_lang=zh-CN 导致）
ALWAYS_DISABLED = {
    'wikidata', 'ahmia', 'torch',
    'brave', 'brave.images', 'brave.videos', 'brave.news',
    'vimeo', 'google news',
    'baidu', 'duckduckgo',
    # duckduckgo 系列同样会触发 CAPTCHA
    'duckduckgo images', 'duckduckgo news', 'duckduckgo videos',
}

# 3. 放开其他引擎（显式设 disabled=False），确保 ALWAYS_DISABLED 中的被禁用
#    注意：SearXNG 在 use_default_settings=true 模式下，engines 段只写 - name: bing
#    而不带 disabled 字段时，会沿用默认配置（bing/baidu 默认是 disabled）。
#    所以必须显式写 disabled: false 才能真正启用。
engines = cfg.get('engines', [])
for eng in engines:
    name = eng.get('name', '')
    if name in ALWAYS_DISABLED:
        eng['disabled'] = True
    else:
        eng['disabled'] = False

with open(path, 'w') as f:
    yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
print(f"[entrypoint-wrapper] 已注入代理 + 放开国外引擎（保留 {len(ALWAYS_DISABLED)} 个禁用）")
PYEOF
else
    echo "[entrypoint-wrapper] 直连模式: 未设置 SEARXNG_PROXY_URL"
    # 直连模式直接用模板原样配置（settings.yml 里已禁用国外引擎）
fi

# 交还给 SearXNG 官方 entrypoint
exec /usr/local/searxng/entrypoint.sh

