---
name: hsk-deploy
description: >
  TRIGGER WHEN: 用户要求"发布网页"、"部署 HTML"、"一键上线"、"分享网页链接"、"生成公网链接"时。
  将静态 HTML/目录/构建产物上传到花生壳文件托管，返回国内可直连、已备案、微信可分享的公网链接。
  免服务器、免域名、免备案，匿名上传后用户认领即长期有效。
trigger: "发布网页|部署网页|部署HTML|一键发布|一键上线|分享网页|网页发布|公网链接|发布到公网|花生壳|hsk|publish webpage|deploy html|share webpage"
license: MIT
version: 1.0.0
source: internal (hermes agent)
---

# 花生壳一键部署 (HSK Deploy)

本技能将静态网页（单文件 HTML、dist 目录、ZIP 压缩包）上传到花生壳文件托管，返回国内可直连的公网链接。

## 🎯 适用场景

- AI 生成的单文件 HTML（PPT 预览、chart、ui-card、报告页、简历、落地页）
- 前端构建产物（dist/、build/）
- ZIP 压缩包（含 index.html + assets）
- **不适用**：需要 Node.js/Python/数据库的动态服务（用 `hsk-cli +tunnel`，见末尾）

## 🔑 凭证说明

**无需预配置凭证**。HSK-CLI 使用匿名资源模式上传，上传成功后返回 `publicUrl` + `resourceId`，用户打开链接完成认领（扫码登录花生壳账号）即长期保留。未认领的资源有时效限制。

## 🛡️ 核心工作流

### 第 0 步：检测与安装 HSK-CLI

```bash
# 检测是否已安装
hsk-cli --version 2>/dev/null || npm install -g @aweray/hsk-cli
```

版本检测（官方推荐，必做）：

```bash
# 检查 npm 包是否有更新
npm outdated -g @aweray/hsk-cli 2>/dev/null && npm update -g @aweray/hsk-cli
# 检查二进制版本
hsk-cli update
```

沙盒/无网环境跳过升级，用现有版本继续。

### 第 1 步：识别输入类型

| 输入 | 命令 | 说明 |
|------|------|------|
| 单个 HTML 文件 | `hsk-cli +host <file.html> --format json` | 最快路径，Agent 生成的单文件页直接传 |
| 目录（dist/） | `hsk-cli +host ./dist --format json` | 原生二进制自动打包 zip 上传 |
| 目录 + 指定入口 | `hsk-cli +host ./dist --entry-file index.html --format json` | 入口非 index.html 时必填 |
| 更新已有资源 | `hsk-cli +host <path> --resource-id <resource_id> --format json` | 用上次返回的 resourceId 覆盖更新 |

### 第 2 步：执行上传

一律加 `--format json` 便于解析输出。沙盒环境**不要**加 `--open`（会被静默拦截）。

```bash
# 单文件（最常见）
hsk-cli +host /path/to/index.html --format json

# 构建产物目录
hsk-cli +host ./dist --format json

# ZIP 压缩包
hsk-cli +host ./project.zip --format json
```

### 第 3 步：解析输出并交付

成功输出（JSON）：

```json
{
  "publicUrl": "https://xxx.oray.com/...",
  "resourceId": "res_xxxxx"
}
```

**向用户呈现（成功）**：

> 文件已上传！
> 公网访问地址：`<publicUrl>`
> 资源 ID：`<resourceId>`（可用于后续更新）
>
> 请复制上方链接在浏览器中打开，按页面提示**激活并认领**资源。
> 认领后可在 [HSK 控制台](https://console-hsk-ng.oray.com/) 查看与管理，链接长期有效。

**纪律**：
- `publicUrl` 视为 opaque string，不要 URL 编码/解码、不要插入空格或换行
- 用**只包含原始 URL** 的代码块单独展示给用户
- 认领前的临时链接有时效，提醒用户尽快认领

## 📋 完整示例

### 场景 1：发布 Agent 生成的单文件 HTML

```bash
# 1. 确认 hsk-cli 已装
hsk-cli --version 2>/dev/null || npm install -g @aweray/hsk-cli

# 2. 上传（假设文件在 ~/.ethan/output/report.html）
hsk-cli +host ~/.ethan/output/report.html --format json

# 3. 解析 JSON 拿到 publicUrl 和 resourceId，呈现给用户
```

### 场景 2：发布构建产物

```bash
# 已 pnpm build，产物在 ./dist
hsk-cli +host ./dist --format json
```

### 场景 3：用 resourceId 更新已有资源（不换链接）

```bash
hsk-cli +host ./dist --resource-id res_xxxxx --format json
```

## 🚫 避坑指南

| 问题 | 原因 | 处理 |
|------|------|------|
| `--open` 无响应 | 沙盒静默拦截 | 去掉 `--open`，让用户手动复制链接 |
| 上传目录失败 | 目录过大或文件数超限 | 单文件 <25MB、总数 <2000、总大小 <100MB |
| 链接打不开 | 用户未认领或已过期 | 提醒用户打开链接完成认领 |
| `npm install -g` 失败 | 权限或网络 | 用 `npx @aweray/hsk-cli +host ...` 临时运行 |
| `host` 失败但生成了 publicUrl | 上传异常但资源已建 | 仍把链接给用户，说明上传异常 |
| 获取 ticket 失败 | 网络问题 | 检查网络，勿无限重试，反馈错误信息 |

## 🔀 与其他发布工具的协作

| 场景 | 推荐 skill | 原因 |
|------|-----------|------|
| 国内分享、微信可开、免服务器 | **hsk-deploy**（本技能） | 已备案域名，国内直连 |
| 海外访问、CI/CD、自定义域名 | vercel-deploy | Vercel 全球 CDN |
| 单张图片/文件外链 | upload-cdn | S3 兼容对象存储 |

生成 HTML 的 skill（ppt-generate、ui-card、chart 等）完成后，可直接调本 skill 一键发布。

## 📦 降级方案：本地动态服务

如果需要发布运行中的本地服务（Node.js/Python/API/WebSocket），`host` 不适用，改用 `tunnel`：

```bash
# 前台保活（捕获到 publicUrl 后提示用户认领）
hsk-cli +tunnel --ip 127.0.0.1 --port 3000 --format json

# 后台模式（CLI 立即退出，隧道持续运行）
hsk-cli +tunnel --ip 127.0.0.1 --port 3000 --detach --format json

# 检查隧道状态
hsk-cli status --format json

# 停止全部后台隧道
hsk-cli tunnel stop --all
```

注意：隧道模式本地服务必须保持运行，临时匿名隧道有效期 24 小时。

## 📚 命令速查

| 命令 | 说明 |
|------|------|
| `hsk-cli +host <path>` | 上传文件/目录托管（首选） |
| `hsk-cli +host <path> --entry-file <file>` | 指定入口文件 |
| `hsk-cli +host <path> --resource-id <id>` | 更新已有资源 |
| `hsk-cli +deploy` | 构建并部署（自动 npm run build） |
| `hsk-cli +tunnel --ip <IP> --port <PORT>` | 内网穿透（动态服务） |
| `hsk-cli status` | 检查隧道资源状态 |
| `hsk-cli platform` | 检测 OS / 架构 |
| `hsk-cli update` | 检查并更新客户端 |
| `hsk-cli skill` | 显示官方 Skill 源文件路径 |
