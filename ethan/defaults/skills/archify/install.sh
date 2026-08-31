#!/usr/bin/env bash
# archify 技能自安装脚本
#
# 作用：从上游 GitHub 仓库拉取 archify 的运行时源码（CLI + 渲染器 + schema + 模板），
#       安装到本技能目录。首次使用 archify 前必须运行一次。
#
# 用法：
#   ./install.sh            # 安装（幂等，已安装且完整则跳过）
#   ./install.sh --force    # 强制重新安装（覆盖现有文件）
#   ./install.sh --check    # 仅检查是否已安装且完整，不下载
#
# 上游信息：
#   repo:  https://github.com/tt-a1i/archify
#   tag:   v2.16.0
#   license: MIT
set -euo pipefail

# 可配置项（如需升级，改 TAG 即可）
REPO_URL="https://github.com/tt-a1i/archify"
TAG="v2.16.0"

# 本脚本所在目录 = 技能目录
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 运行时文件安装到的目标目录（技能目录下的 _runtime/，git 忽略）
RUNTIME_DIR="$SKILL_DIR/_runtime"
# 已安装版本标记文件
VERSION_FILE="$RUNTIME_DIR/.archify-version"

# 安装后必须存在的关键文件（用于完整性校验）
REQUIRED_FILES=(
  "bin/archify.mjs"
  "assets/template.html"
  "schemas/architecture.schema.json"
  "schemas/common.schema.json"
)

MODE="install"
if [ "${1:-}" = "--force" ]; then
  MODE="force"
elif [ "${1:-}" = "--check" ]; then
  MODE="check"
elif [ -n "${1:-}" ]; then
  echo "未知参数: $1" >&2
  echo "用法: $0 [--force|--check]" >&2
  exit 2
fi

log() { printf '\033[1;34m[archify]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[archify]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[1;31m[archify]\033[0m %s\n' "$*" >&2; }

# 校验 _runtime 是否完整
is_complete() {
  [ -f "$VERSION_FILE" ] || return 1
  [ "$(cat "$VERSION_FILE")" = "$TAG" ] || return 1
  local f
  for f in "${REQUIRED_FILES[@]}"; do
    [ -f "$RUNTIME_DIR/$f" ] || return 1
  done
  return 0
}

# 检查依赖
check_deps() {
  command -v git >/dev/null 2>&1 || { err "需要 git，请先安装 git"; exit 1; }
}

if [ "$MODE" = "check" ]; then
  if is_complete; then
    log "已安装且完整（${TAG}）"
    exit 0
  else
    warn "未安装或不完整，请运行: $0"
    exit 1
  fi
fi

if [ "$MODE" != "force" ] && is_complete; then
  log "已安装 ${TAG}，跳过（用 --force 可强制重装）"
  exit 0
fi

check_deps

# 用临时目录浅克隆上游，再拷贝 archify/ 子目录
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

log "拉取上游 $REPO_URL @ $TAG ..."
git clone --depth 1 --branch "$TAG" "$REPO_URL" "$TMP_DIR/src" >/dev/null 2>&1 || {
  err "拉取失败：$REPO_URL @ $TAG"
  exit 1
}

SRC="$TMP_DIR/src/archify"
if [ ! -f "$SRC/SKILL.md" ] && [ ! -f "$SRC/bin/archify.mjs" ]; then
  err "上游仓库结构异常：未找到 archify/ 子目录（bin/archify.mjs）"
  exit 1
fi

log "校验上游关键文件..."
for f in "${REQUIRED_FILES[@]}"; do
  [ -f "$SRC/$f" ] || { err "上游缺少关键文件: $f"; exit 1; }
done

log "安装到 $RUNTIME_DIR ..."
rm -rf "$RUNTIME_DIR"
mkdir -p "$RUNTIME_DIR"
# 只拷贝运行时必需内容，排除测试、开发工具、以及成品 HTML 样例
# （examples/*.html 是给人看的渲染结果，每个 700KB+，agent 生成图用不到，
#   保留 *.json 样例即可；排除它们可省 3.5MB 并避免被误读进上下文）
rsync -a \
  --exclude='test/' \
  --exclude='package-lock.json' \
  --exclude='examples/*.html' \
  "$SRC/" "$RUNTIME_DIR/"

# 写版本标记
echo "$TAG" > "$VERSION_FILE"

# 二次校验（拷贝后）
if ! is_complete; then
  err "安装后校验失败，安装内容不完整"
  exit 1
fi

log "完成。archify CLI 位于 $RUNTIME_DIR/bin/archify.mjs"
log "验证: node $RUNTIME_DIR/bin/archify.mjs doctor"
