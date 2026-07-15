#!/usr/bin/env bash
# 构建静态文档数据：将 docs/*.md 转为 JSON 并复制图片到 web/public/docs-data/
# GitHub Pages CI 和本地 `next build` 前运行此脚本。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCS_DIR="$REPO_ROOT/docs"
OUT_DIR="$REPO_ROOT/web/public/docs-data"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# 1. 每个 .md 文件 → {slug}.json
for f in "$DOCS_DIR"/*.md; do
  [ -f "$f" ] || continue
  filename="$(basename "$f")"
  slug="${filename%.md}"

  # 用 python 生成 JSON（保证转义正确）
  python3 -c "
import json, sys
with open(sys.argv[1], 'r') as fh:
    content = fh.read()
print(json.dumps({'slug': sys.argv[2], 'content': content}, ensure_ascii=False))
" "$f" "$slug" > "$OUT_DIR/$slug.json"
done

# 2. 处理子目录下的 .md（如 browser/overview.md → browser--overview.json）
for f in $(find "$DOCS_DIR" -mindepth 2 -name "*.md" 2>/dev/null); do
  rel="${f#$DOCS_DIR/}"
  # browser/overview.md → browser--overview
  slug="$(echo "${rel%.md}" | tr '/' '--')"
  python3 -c "
import json, sys
with open(sys.argv[1], 'r') as fh:
    content = fh.read()
print(json.dumps({'slug': sys.argv[2], 'content': content}, ensure_ascii=False))
" "$f" "$slug" > "$OUT_DIR/$slug.json"
done

# 3. 复制图片
if [ -d "$DOCS_DIR/images" ]; then
  cp -r "$DOCS_DIR/images" "$OUT_DIR/images"
fi

echo "✓ Static docs prepared: $(ls "$OUT_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ') pages, images/ copied"
