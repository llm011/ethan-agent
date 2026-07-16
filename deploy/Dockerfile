# Ethan Agent — Backend + Web UI (单容器模式)
# 多阶段构建：Node 编译前端 → Python 运行时
# 适合 x86_64 和 arm64（Apple Silicon / NAS）

# ── Stage 1: 构建 Web UI（静态导出） ──────────────────────────
FROM node:20-alpine AS web-builder

WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install --frozen-lockfile

COPY web/ .
ENV NEXT_TELEMETRY_DISABLED=1
# export 模式：产出纯静态文件，由 FastAPI 直接 serve
ENV NEXT_OUTPUT=export
RUN pnpm run build

# ── Stage 2: Python 运行时 ────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# 系统依赖
# - gcc/make：sqlite-vec / uvloop 原生编译依赖
# - ripgrep：rg 搜索工具
# - fd-find：fd 文件搜索工具（ln -s 为 fd）
# - curl/git：uv 安装 + 依赖获取
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc make \
    ripgrep fd-find \
    curl git ca-certificates \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# 先复制依赖文件，利用 Docker 层缓存
COPY pyproject.toml uv.lock ./

# 安装 Python 依赖（不安装项目本身）
RUN uv sync --frozen --no-dev --no-install-project

# 复制源码和元数据文件（打包需要 README）
COPY ethan/ ./ethan/
COPY README.md README_CN.md ./

# 从 Stage 1 拷入 Web UI 静态产物（放在 ethan/ 之外，避免 volume mount 覆盖）
COPY --from=web-builder /web/out ./web_dist

# 安装项目本身
RUN uv sync --frozen --no-dev

# 数据目录挂载点（记忆、会话、Skills、配置）
# 代码使用 Path.home() / ".ethan"，容器内 root home = /root
VOLUME /root/.ethan

ENV WEB_DIST_PATH=/app/web_dist
EXPOSE 8900

CMD ["uv", "run", "python", "-m", "ethan.interface.cli", "serve"]
