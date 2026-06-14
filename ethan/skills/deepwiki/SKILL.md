---
name: deepwiki
description: "通过 DeepWiki 查询任意 GitHub 仓库的文档、架构分析和 AI 问答。适用于理解库的用法、分析开源项目结构。"
trigger: "deepwiki|github docs|how does|look up docs|analyze repo|分析仓库|查文档|github 仓库|代码分析|开源项目"
---

# deepwiki

通过 DeepWiki 查询 GitHub 公开仓库的文档，支持目录浏览、全文获取和 AI 问答。需要 Node.js 已安装。

## 命令

| 命令 | 用法 | 说明 |
|------|------|------|
| `toc` | `npx @seflless/deepwiki toc <owner/repo>` | 获取文档目录结构 |
| `wiki` | `npx @seflless/deepwiki wiki <owner/repo>` | 获取完整文档 |
| `ask` | `npx @seflless/deepwiki ask <owner/repo> "<question>"` | AI 问答 |
| `ask` | `npx @seflless/deepwiki ask <repo1> <repo2> "<question>"` | 跨仓库问答（最多 10 个） |

## 常用参数

| 参数 | 作用 |
|------|------|
| `--json` | 输出 JSON 格式（适合管道处理） |
| `-q, --quiet` | 不显示进度动画 |

## 使用示例

```bash
# 了解库的结构
npx @seflless/deepwiki toc facebook/react

# 获取完整文档保存到文件
npx @seflless/deepwiki wiki oven-sh/bun --json > bun-docs.json

# 问具体问题
npx @seflless/deepwiki ask anthropics/claude-code "How does the tool permission system work?"

# 跨项目问题
npx @seflless/deepwiki ask facebook/react vercel/next.js "How do server components work?"
```

## 建议工作流

1. 先用 `toc` 了解文档结构
2. 再用 `ask` 问具体问题（比 `wiki` 快，token 消耗少）
3. 需要完整参考时用 `wiki --json` 保存到文件再 `file_read`
