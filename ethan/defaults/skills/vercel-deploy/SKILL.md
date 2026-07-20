---
name: vercel-deploy
description: >
  TRIGGER WHEN: 用户要求"部署网页"、"发布到 Vercel"、"做个工具页面并上线"时。
  处理 Web 项目的安全部署，支持非交互式 Token 验证及通用宿主项目管理。
license: MIT
version: 1.0.0
source: internal (hermes agent)
---

# Vercel 极速部署 (Vercel Deploy)

本技能用于将静态页面或 Web 应用快速部署至 Vercel 环境。

## 🔑 密钥配置 (Secrets)

凭证文件优先级（按顺序查找，命中即停）：

1. `~/.ethan/.secrets/vercel.env`（推荐，独立密钥文件）
2. `~/.ethan/.env`（统一 env 文件）

需要以下环境变量：

- `VERCEL_TOKEN` —— Vercel API 访问令牌（**必填**）
- `VERCEL_ORG_ID` —— 组织 ID（首次 `vercel link` 后由本地 `.vercel/` 写入，可选）
- `VERCEL_PROJECT_ID` —— 项目 ID（首次 `vercel link` 后由本地 `.vercel/` 写入，可选）

加载方式（执行部署前必须 source）：

```bash
[ -f ~/.ethan/.secrets/vercel.env ] && source ~/.ethan/.secrets/vercel.env \
  || ([ -f ~/.ethan/.env ] && source ~/.ethan/.env)
```

**严禁在 SKILL.md 或终端输出中明文写入 Token 值。**

## 🛡️ 核心工作流 (Workflow)

### 1. 宿主模式 (Host Project)

默认将页面存入 `~/.ethan/web/tools/` 子目录，统一部署 `~/.ethan/web` 根项目以减少 Vercel 项目数。

### 2. 构建与部署 (Build & Deploy)

非交互式部署：

```bash
npx vercel --prod --yes --token "$VERCEL_TOKEN" --cwd "$HOME/.ethan/web"
```

部署完成后必须提取并返回 `https://...vercel.app` 链接。

### 3. pnpm 项目示例 (pnpm Workflow)

用户偏好 pnpm。对于 pnpm 项目：

```bash
# 1. 构建
pnpm install --frozen-lockfile && pnpm build

# 2. 部署构建产物（如 dist/ 或 build/）
npx vercel deploy --prod --yes --token "$VERCEL_TOKEN" --cwd ./dist

# 3. 若需显式传递组织/项目（覆盖 .vercel/ 本地配置）
VERCEL_ORG_ID="$VERCEL_ORG_ID" \
VERCEL_PROJECT_ID="$VERCEL_PROJECT_ID" \
npx vercel --prod --yes --token "$VERCEL_TOKEN"
```

## 避坑指南 (Gotchas)

- **本地路径**: 必须使用绝对路径传递给 `--cwd`（`~` 不会被 vercel CLI 展开，需用 `$HOME` 或实际路径）。
- **Link 错误**: 若项目未关联，加入 `--force` 参数或提示用户运行 `vercel link`。
- **环境污染**: 优先使用 `npx vercel` 而非全局安装的 `vercel`，避免版本污染。
- **pnpm 检测**: 通过 Vercel 自动构建时，确保 `package.json` 中 `packageManager` 字段为 `pnpm@<version>`，以触发 Vercel 的 pnpm 自动检测。
