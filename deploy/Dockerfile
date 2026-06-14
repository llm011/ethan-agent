# Ethan Agent — Backend
# Python 3.12 + uv，适合 x86_64 和 arm64（Apple Silicon / NAS）
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

# 复制源码
COPY ethan/ ./ethan/
COPY bin/ ./bin/

# 安装项目本身（editable install）
RUN uv sync --frozen --no-dev

# 数据目录挂载点（记忆、会话、Skills、配置）
# 代码使用 Path.home() / ".ethan"，容器内 root home = /root
VOLUME /root/.ethan

EXPOSE 8900

CMD ["uv", "run", "python", "-m", "ethan.interface.cli", "serve"]
