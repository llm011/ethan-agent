---
name: lark-doc
version: 1.0.0
trigger: "飞书文档|读文档|解析飞书|lark doc|feishu doc|飞书云文档|docx|读取文档|下载文档|导出文档|文档转markdown"
description: "读取飞书云文档并导出为标准 Markdown 文件，图片可选上传 CDN 转为公开外链。支持表格、代码块、列表等富文本格式。当用户要读取/解析/导出飞书文档时使用。"
metadata:
  requires:
    bins: ["lark-cli"]
---

# lark-doc

读取飞书云文档，导出为可在任意 Markdown 编辑器打开的 `.md` 文件。

## 前置检查

**必读** [`lark-shared/SKILL.md`](../lark-shared/SKILL.md) — 了解 lark-cli 认证和 `--as` 身份切换。

## 基本用法

```bash
python ~/.ethan/skills/lark-doc/scripts/fetch_doc.py "https://xxx.feishu.cn/docx/TOKEN" ./output.md
```

脚本会：
1. 用 `lark-cli docs +fetch --api-version v2 --doc-format markdown` 获取文档内容
2. 扫描 markdown 中所有图片引用（`![](feishu_url)`）
3. 如果检测到 `upload-cdn` 凭证（`CDN_ENDPOINT` 等环境变量），自动下载图片并上传 CDN，替换为公开 URL
4. 如果没有 CDN 凭证，保留飞书原始 URL 并在文件末尾附上说明
5. 写出 `.md` 文件

## 凭证依赖

| 依赖 | 必须 | 说明 |
|------|------|------|
| `lark-cli` 用户登录 | 是 | `lark-cli auth login --scope "docx:document:readonly"` |
| `upload-cdn` 密钥 | 否 | 有则图片自动上传 CDN；无则图片 URL 保留飞书原始链接（本地可能无法加载） |

## 检测 CDN 是否可用

```bash
test -n "$CDN_ENDPOINT" && test -n "$CDN_ACCESS_KEY" && echo CDN_READY || echo CDN_MISSING
```

- `CDN_READY` → 图片自动上传，markdown 中为公开 URL
- `CDN_MISSING` → 提示用户配置 `upload-cdn` skill 的密钥（参见 `upload-cdn` skill），或告知图片链接在本地编辑器中可能无法显示

## 决策流程

1. 用户给出飞书文档 URL 或 token
2. 检查 lark-cli 登录状态（`lark-cli docs +fetch --api-version v2 --doc "URL" --doc-format markdown`）
3. 检测 CDN 凭证，告知用户图片处理方式
4. 运行脚本，输出 `.md` 文件
5. 告知用户文件位置及图片状态

## 直接调用 lark-cli（不用脚本）

只需要查看文档内容、不需要保存文件时：

```bash
# 查看内容
lark-cli docs +fetch --api-version v2 --doc "URL" --doc-format markdown

# 只看目录结构
lark-cli docs +fetch --api-version v2 --doc "URL" --scope outline --max-depth 3

# 按关键词查找
lark-cli docs +fetch --api-version v2 --doc "URL" --scope keyword --keyword "关键词"
```

## 关于表格

`--doc-format markdown` 会把飞书表格渲染为标准 Markdown 表格语法（GFM），在 Obsidian、Typora、VS Code 等编辑器中可正常显示。
