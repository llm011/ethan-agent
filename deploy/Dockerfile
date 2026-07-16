# Ethan Agent — 生产单容器镜像（API + Web UI 同端口 8900）
# 多阶段构建：Node 编译前端静态导出 → Python 运行时直接 serve
#
# 平台：linux/amd64 + linux/arm64（基础镜像均多平台，CI 用 buildx 构建）
# 数据：VOLUME /root/.ethan（记忆、会话、Skills、配置）
# 启动：ethan setup 幂等初始化（无 TTY 时仅初始化目录/config）→ ethan serve

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

# 可选 apt 镜像源：国内网络构建时传 --build-arg APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
# CI（GitHub 机房）默认官方源。
ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then \
      sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
      sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi

# 系统依赖
# - gcc/make：sqlite-vec / uvloop 原生编译依赖
# - ripgrep：rg 搜索工具
# - fd-find：fd 文件搜索工具（ln -s 为 fd）
# - curl/git：uv 安装 + 依赖获取 + healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc make \
    ripgrep fd-find \
    curl git ca-certificates \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（安装脚本自动适配 amd64/arm64）
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# 先复制依赖文件，利用 Docker 层缓存
COPY pyproject.toml uv.lock ./

# 安装 Python 依赖（不安装项目本身）
RUN uv sync --frozen --no-dev --no-install-project

# 复制源码和元数据文件（打包需要 README）
COPY ethan/ ./ethan/
COPY README.md README_CN.md ./

# 从 Stage 1 拷入 Web UI 静态产物。
# 放 /app/web_dist（ethan/ 之外）：一是不进 Python 包、避免 uv sync 重装时挪动；
# 二是避免本地开发 mount ethan/ 源码时把前端产物覆盖掉。配合 WEB_DIST_PATH 指过来。
COPY --from=web-builder /web/out ./web_dist

# 安装项目本身
RUN uv sync --frozen --no-dev

# venv bin 入 PATH：ethan 命令直接可用
ENV PATH="/app/.venv/bin:$PATH"
# 告诉 FastAPI 前端静态文件位置（默认找包内 ethan/web_dist，这里外置了）
ENV WEB_DIST_PATH=/app/web_dist

# 数据目录挂载点（记忆、会话、Skills、配置）
# 代码使用 Path.home() / ".ethan"，容器内 root home = /root
VOLUME /root/.ethan

EXPOSE 8900

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8900/api/health || exit 1

# setup 幂等初始化（首次创建 ~/.ethan 目录、config、默认技能；
# 无 TTY 环境下不会进入交互菜单），随后前台启动服务。
# 启动时打印 Web UI token，方便 docker logs 里查看。
CMD ["bash", "-c", "\
    ethan setup \
    && echo '' \
    && echo \"🔑 Web UI Token: $(awk '/auth_token:/{print $2}' /root/.ethan/config.yaml 2>/dev/null || echo '(未设置)')\" \
    && echo '' \
    && exec ethan serve --port 8900"]
