#!/usr/bin/env bash
# 在干净 Docker 环境中测试 ethan（模拟新用户）
set -e

IMAGE="ethan-dev"
DOCKERFILE="deploy/Dockerfile.dev"
WITH_CONFIG=false
SHELL_MODE=false

# 解析选项
while getopts "cs" opt; do
  case $opt in
    c) WITH_CONFIG=true ;;
    s) SHELL_MODE=true ;;
    *) echo "用法: $0 [-c] [-s] [command...]"; echo "  -c  纯净模式，不映射本地 ~/.ethan/config.yaml"; echo "  -s  进入 bash（默认启动 ethan serve）"; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

# 检测是否需要重新 build（Dockerfile 或 pyproject.toml 比镜像新）
needs_build() {
  if ! docker image inspect "$IMAGE" &>/dev/null; then
    return 0
  fi
  img_ts=$(docker image inspect "$IMAGE" --format '{{.Created}}' 2>/dev/null)
  img_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${img_ts%%.*}" "+%s" 2>/dev/null || echo 0)
  for f in "$DOCKERFILE" deploy/Dockerfile pyproject.toml uv.lock; do
    [ -f "$f" ] && [ "$(stat -f %m "$f")" -gt "$img_epoch" ] && return 0
  done
  return 1
}

if needs_build; then
  echo "🔨 Building $IMAGE ..."
  docker build -t "$IMAGE" -f "$DOCKERFILE" . -q
else
  echo "✓ 镜像已是最新，跳过 build"
fi

# 构造 docker run 参数（serve 模式不需要 TTY，shell 模式需要 -it）
if [ "$SHELL_MODE" = true ]; then
  DOCKER_ARGS=(-it --rm -v "$(pwd)/ethan:/app/ethan" -p "${ETHAN_PORT:-8911}:8900")
else
  DOCKER_ARGS=(--rm -v "$(pwd)/ethan:/app/ethan" -p "${ETHAN_PORT:-8911}:8900")
fi

# 从本地 ~/.ethan/config.yaml 提取模型配置和对应 provider key 传入容器
if [ "$WITH_CONFIG" = true ]; then
  echo "🧹 纯净模式"
else
  LOCAL_CONFIG="$HOME/.ethan/config.yaml"
  if [ -f "$LOCAL_CONFIG" ]; then
    # 一次性提取所有需要的环境变量（KEY=VALUE 格式，每行一个）
    _envs=$(python3 -c "
import yaml, sys
with open('$LOCAL_CONFIG') as f:
    c = yaml.safe_load(f)
providers = c.get('providers', {})
defaults = c.get('defaults', {})
models = c.get('models', [])

# defaults
model = defaults.get('model', '')
lite_model = defaults.get('lite_model', '')
if model:
    print(f'AGENT_DEFAULT_MODEL={model}')
if lite_model:
    print(f'AGENT_LITE_MODEL={lite_model}')

# 找出 default model 和 lite_model 用到的 provider
needed_providers = set()
for m in models:
    if m.get('id') in (model, lite_model):
        needed_providers.add(m.get('provider', ''))
        for fp in m.get('fallback_providers', []):
            needed_providers.add(fp)

# 提取对应 provider 的 key
for pname, pcfg in providers.items():
    if not needed_providers or pname in needed_providers:
        key = pcfg.get('api_key', '')
        url = pcfg.get('base_url', '') or ''
        if key:
            env_prefix = pname.upper().replace('-', '_')
            if pname == 'anthropic':
                print(f'ANTHROPIC_API_KEY={key}')
                if url: print(f'ANTHROPIC_BASE_URL={url}')
            elif pname == 'openai_compat' or pcfg.get('type') == 'openai_compat':
                print(f'OPENAI_API_KEY={key}')
                if url: print(f'OPENAI_BASE_URL={url}')
" 2>/dev/null || true)
    while IFS= read -r line; do
      [ -n "$line" ] && DOCKER_ARGS+=(-e "$line")
    done <<< "$_envs"
  fi
fi

# 默认命令：setup 初始化
INIT_CMD='uv run ethan setup && mkdir -p ~/.ethan/memory && echo "[{\"text\":\"dev environment\",\"confidence\":1.0,\"source\":\"dev-script\",\"category\":\"preference\"}]" > ~/.ethan/memory/facts.json'

HOST_PORT="${ETHAN_PORT:-8911}"

if [ $# -gt 0 ]; then
  echo "🚀 docker run → $*"
  exec docker run "${DOCKER_ARGS[@]}" "$IMAGE" \
    bash -c "$INIT_CMD && uv run $*"
elif [ "$SHELL_MODE" = true ]; then
  echo "🚀 docker run → ethan setup && bash"
  exec docker run "${DOCKER_ARGS[@]}" "$IMAGE" \
    bash -c "$INIT_CMD && echo 'alias ethan=\"uv run ethan\"' >> ~/.bashrc && exec bash"
else
  echo "🚀 ethan serve 启动中，访问 http://localhost:${HOST_PORT}/"
  exec docker run "${DOCKER_ARGS[@]}" "$IMAGE" \
    bash -c "$INIT_CMD && uv run ethan serve --port 8900"
fi
