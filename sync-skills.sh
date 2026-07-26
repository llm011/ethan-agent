#!/usr/bin/env bash
# 同步内置技能源码到 ~/.ethan/skills/
#
# 用法:
#   ./sync-skills.sh              # 同步全部内置技能
#   ./sync-skills.sh feishu-writer  # 只同步指定技能
#   ./sync-skills.sh -l           # 仅列出差异，不实际拷贝（dry-run）
#
# 同步规则（与 ethan/core/config.py::_init_default_skills 对齐）:
#   - SKILL.md: 源比目标新则覆盖
#   - references/: 源比目标新则覆盖，不删除用户自建文件
#   - scripts/: 不动（用户可能改过凭证路径等本地配置）
#   - 若目标是符号链接（开发挂载），跳过
set -e

SRC_DIR="$(cd "$(dirname "$0")" && pwd)/ethan/defaults/skills"
DST_DIR="$HOME/.ethan/skills"
DRY_RUN=false

while getopts "l" opt; do
  case $opt in
    l) DRY_RUN=true ;;
    *) echo "用法: $0 [-l] [skill_name ...]"; echo "  -l  dry-run，仅列出差异"; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

if [ ! -d "$SRC_DIR" ]; then
  echo "错误: 源目录不存在 $SRC_DIR" >&2
  exit 1
fi
mkdir -p "$DST_DIR"

# 选定要同步的技能列表
if [ $# -gt 0 ]; then
  SKILLS=("$@")
else
  SKILLS=( $(ls -1 "$SRC_DIR") )
fi

synced=0
skipped=0
for name in "${SKILLS[@]}"; do
  src="$SRC_DIR/$name"
  dst="$DST_DIR/$name"

  [ ! -d "$src" ] && { echo "跳过: $name (源不存在)"; continue; }

  # 符号链接（开发挂载）跳过
  if [ -L "$dst" ]; then
    echo "跳过: $name (符号链接 → $(readlink "$dst"))"
    skipped=$((skipped + 1))
    continue
  fi

  # 首次拷贝：整个目录 copytree
  if [ ! -d "$dst" ]; then
    if $DRY_RUN; then
      echo "新增: $name/ (首次拷贝)"
    else
      cp -R "$src" "$dst"
      echo "新增: $name/ (首次拷贝)"
    fi
    synced=$((synced + 1))
    continue
  fi

  # 增量同步：SKILL.md
  if [ -f "$src/SKILL.md" ]; then
    if [ ! -f "$dst/SKILL.md" ] || [ "$src/SKILL.md" -nt "$dst/SKILL.md" ]; then
      if $DRY_RUN; then
        echo "更新: $name/SKILL.md"
      else
        cp -p "$src/SKILL.md" "$dst/SKILL.md"
        echo "更新: $name/SKILL.md"
      fi
      synced=$((synced + 1))
    fi
  fi

  # 增量同步：references/（仅添加/更新，不删除）
  if [ -d "$src/references" ]; then
    mkdir -p "$dst/references"
    for ref in "$src"/references/*; do
      [ -f "$ref" ] || continue
      dst_ref="$dst/references/$(basename "$ref")"
      if [ ! -f "$dst_ref" ] || [ "$ref" -nt "$dst_ref" ]; then
        if $DRY_RUN; then
          echo "更新: $name/references/$(basename "$ref")"
        else
          cp -p "$ref" "$dst_ref"
          echo "更新: $name/references/$(basename "$ref")"
        fi
      fi
    done
  fi
done

echo ""
if $DRY_RUN; then
  echo "Dry-run 完成: $synced 个待同步, $skipped 个跳过"
else
  echo "同步完成: $synced 个更新, $skipped 个跳过"
fi
echo "提示: scripts/ 不自动同步（用户可能改过本地配置）"
