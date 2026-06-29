---
name: lark-doc
version: 1.1.0
trigger: "飞书文档|读文档|解析飞书|lark doc|feishu doc|飞书云文档|docx|wiki|读取文档|下载文档|导出文档|文档转markdown|飞书wiki|知识库文档"
description: "读取飞书云文档（docx 和 wiki 均支持）并导出为标准 Markdown 文件，图片可选上传 CDN 转为公开外链。支持表格、代码块、列表等富文本格式。当用户要读取/解析/导出飞书文档或 wiki 页面时使用。"
metadata:
  requires:
    bins: ["lark-cli"]
---

# lark-doc

读取飞书云文档，导出为可在任意 Markdown 编辑器打开的 `.md` 文件。

## 前置检查

**必读** [`lark-shared/SKILL.md`](../lark-shared/SKILL.md) — 了解 lark-cli 认证和 `--as` 身份切换。

## ⚠️ Wiki 链接也直接用本 skill，不要绕到 lark-wiki

`lark-cli docs +fetch --api-version v2` 同时支持 `/docx/` 和 `/wiki/` URL，内部自动处理 wiki token 路由：

```bash
# docx 文档
python ~/.ethan/skills/lark-doc/scripts/fetch_doc.py "https://xxx.feishu.cn/docx/TOKEN" ./out.md

# wiki 页面 — 完全相同的命令，lark-cli 自动识别
python ~/.ethan/skills/lark-doc/scripts/fetch_doc.py "https://xxx.feishu.cn/wiki/TOKEN" ./out.md
```

**不要**先用 `lark-wiki` skill 的 `wiki +node-get` / `wiki spaces get_node` 拿 docx token，那是手动路径，比这更繁琐且容易失败。

## ⚠️ 必须用脚本导出，不能直接用 shell 调 lark-cli

**不要**通过 shell 工具直接调 `lark-cli docs +fetch` 来导出文件——shell 工具有 8000 字符输出截断，大文档会丢失大量内容。

**必须**用下面的脚本，脚本内部用 subprocess 调 lark-cli（绕开截断），stdout 只输出文件路径：

```bash
python ~/.ethan/skills/lark-doc/scripts/fetch_doc.py "https://xxx.feishu.cn/docx/TOKEN" ./output.md
```

脚本会：
1. 内部调 `lark-cli docs +fetch --api-version v2 --doc-format markdown` 获取完整文档（不受 shell 截断影响）
2. 扫描图片，有 CDN 凭证则上传替换为公开 URL，无则保留飞书链接
3. 检测视频/附件 Token，下载到 `./media/` 目录并替换为本地链接
4. 写出完整 `.md` 文件，stdout 只打印文件路径

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
