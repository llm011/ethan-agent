# Ethan Agent — Backend
# Python 3.12 + uv，适合 x86_64 和 arm64（Apple Silicon / NAS）
FROM python:3.12-slim

WORKDIR /app

# 系统依赖：ripgrep（rg 工具）、curl、git
RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:/root/.local/bin:$PATH"

# 先复制依赖文件，利用 Docker 层缓存
COPY pyproject.toml uv.lock ./

# 安装 Python 依赖（不安装项目本身，节省时间）
RUN uv sync --frozen --no-dev --no-install-project

# 复制源码
COPY ethan/ ./ethan/
COPY bin/ ./bin/

# 安装项目
RUN uv sync --frozen --no-dev

# 持久化数据目录（~/.ethan）挂载到容器外部
ENV ETHAN_HOME=/data/ethan
ENV ETHAN_WORKSPACE=/data/ethan

# 对外暴露 API 端口
EXPOSE 8900

# 默认启动 API 服务
CMD ["uv", "run", "python", "-m", "ethan.interface.cli", "serve", "--host", "0.0.0.0", "--port", "8900"]
