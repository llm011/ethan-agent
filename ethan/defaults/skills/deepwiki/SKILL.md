---
name: deepwiki
description: "通过 DeepWiki 查询任意 GitHub 仓库的文档、架构分析和 AI 问答。适用于理解库的用法、分析开源项目结构。"
trigger: "deepwiki|github docs|how does|look up docs|analyze repo|分析仓库|查文档|github 仓库|代码分析|开源项目"
---

# deepwiki

通过 DeepWiki 查询 GitHub 公开仓库的文档，支持目录浏览、全文获取和 AI 问答。需要 Node.js 已安装。

## ⚠️ 必读：命令必须带 `-y`

agent 的 shell 是**非交互**子进程。`npx <包>` 首次运行会交互式询问「Ok to proceed? (y)」安装确认，
非交互环境下这个提示会一直挂住直到超时——这是"deepwiki 跑不通"的根因。
**所有命令一律用 `npx -y @seflless/deepwiki ...`**（`-y` 跳过安装确认），再加 `-q` 去掉进度动画。
`ask`/`wiki` 可能要十几秒到几十秒，给 shell 工具留足超时（如 180s）。

## 命令

| 命令 | 用法 | 说明 |
|------|------|------|
| `toc` | `npx -y @seflless/deepwiki toc <owner/repo> -q` | 获取文档目录结构 |
| `wiki` | `npx -y @seflless/deepwiki wiki <owner/repo> -q` | 获取完整文档 |
| `ask` | `npx -y @seflless/deepwiki ask <owner/repo> "<question>" -q` | AI 问答 |
| `ask` | `npx -y @seflless/deepwiki ask <repo1> <repo2> "<question>" -q` | 跨仓库问答（最多 10 个） |

## 常用参数

| 参数 | 作用 |
|------|------|
| `-y`（给 npx） | 跳过 npx 首次安装确认，**非交互环境必须带** |
| `--json` | 输出 JSON 格式（适合管道处理） |
| `-q, --quiet` | 不显示进度动画 |

## 使用示例

```bash
# 了解库的结构
npx -y @seflless/deepwiki toc facebook/react -q

# 获取完整文档保存到文件（wiki 输出很长，务必重定向到文件再 file_read，避免 shell 输出截断）
npx -y @seflless/deepwiki wiki oven-sh/bun --json -q > /tmp/bun-docs.json

# 问具体问题
npx -y @seflless/deepwiki ask anthropics/claude-code "How does the tool permission system work?" -q

# 跨项目问题
npx -y @seflless/deepwiki ask facebook/react vercel/next.js "How do server components work?" -q
```

## 建议工作流

1. 先用 `toc` 了解文档结构
2. 再用 `ask` 问具体问题（比 `wiki` 快，token 消耗少）
3. 需要完整参考时用 `wiki --json -q > /tmp/xxx.json` 保存到文件再 `file_read`（wiki 全文常超 shell 输出上限，直接打印会被截断）
