# order-info-extension 服务端重写方案：去 n8n + lark CLI + AWS 最省基建

> 分析对象：`~/code-old/browser-extensions/libra/order-info-extension`（分支 `feat/use-n8n`，工作区有未提交改动）
> 分析时间：2026-09-25
> 结论强度：架构选型已用**本机真实 `lark-cli` v1.0.90 实测验证**（非文档推测）；成本数字取自 **AWS 官方 Pricing API 实时价目表**，非记忆值。

---

## 0. 结论速览（TL;DR）

| 问题 | 结论 |
|---|---|
| n8n 到底做了什么 | **只有 4 件事**：① 飞书鉴权（tenant_access_token 换取与刷新）② `/read-data` 读表 ③ `/update-data` 离散范围写表 ④ `/write-image-to-sheet` 写图。**零业务逻辑、零清洗、零去重**——清洗和去重全在插件前端。 |
| 能否用 lark CLI 直接实现 | **可以，但不是"扩展直连 lark CLI"**——CLI 是进程，浏览器扩展调不动它。正确形态：**把 n8n 换成一个跑在 Lambda 上的 Node 函数，该函数 shell 出 `lark-cli`**，扩展只改一个 URL。 |
| 为什么不让扩展直连飞书 OpenAPI | **可以但更贵**：需要自己实现 token 换取/刷新/并发去重（tenant token 有效期 2h，扩展无安全的地方放 app_secret）。lark CLI 把这层接过去了。 |
| 推荐架构 | **Lambda (arm64) + Function URL + DynamoDB(按需) + Secrets Manager**，全 serverless，无常驻实例。SAM 一条命令部署。 |
| 月成本 | **$0.00 ~ $0.30/月**（稳态 **$0**，全在免费额度内）。若嫌 Secrets Manager 的 $0.40/月贵，改用 Lambda 加密环境变量可压到 **$0.00**。 |
| 要不要 EC2 t4g.nano | **不要**。t4g.nano 常驻约 $4.3/月（含 EBS），是本方案上限的 14 倍，且要为"每天几次抓取"养一台机器。 |
| 最大的工作量在哪 | **不在服务端**（服务端 ~300 行），**在扩展前端**：有 3 处必须先修的真实缺陷（见 §6），否则换完后端依然写不对表。 |

**一句话**：n8n 只当了 4 个薄端点的代理，用 **一个 arm64 Lambda（约 300 行 Node）内部调用 lark-cli** 完整替代，月成本从"一台常驻 n8n 实例"降到 **$0**，扩展侧只需改一个 base URL。

---

## 1. 现有 n8n 逻辑清单

### 1.1 契约（从扩展源码反向还原）

所有调用集中在 `src/services/n8nService.ts`，`baseUrl = https://n8n.ethanlyn.com/webhook/libra`，认证是**固定明文 token** `Authorization: d7MKuM5kh5CLSnK`。

| 端点 | 方法 | 入参 | 出参 | 调用方 |
|---|---|---|---|---|
| `/create-table` | POST | `{name}` | `{folder_token, spreadsheet_token, title, url}` | `Layout.tsx:113,138` |
| `/read-data` | POST | `{token, scope}` | `{values: any[][]}` | `feishuService.ts`（读 `Q1:Q1000`）、`walmartScraping.ts:337`（读 `!P:Q`） |
| `/update-data` | POST | `{token, scopes: string[], data: string[][]}` | `{revision, spreadsheetToken, updatedCells, updatedColumns, updatedRange, updatedRows}` | `feishuService.ts` 批量/单条更新 |
| `/write-image-to-sheet` | POST | `{token, scope, url}` | `{revision, spreadsheetToken, updateRange}` | `feishuService.ts` |

> 注：旧 Azure 版 `server/src/services/feishuService.js` 里还存在 `/get-record`，但**当前扩展已不再调用**（v3 迁移后废弃），不在重写范围内。

### 1.2 n8n 工作流真正承担的逻辑

| # | 逻辑 | 是否业务 | 替代方案 |
|---|---|---|---|
| 1 | **飞书鉴权**：用 app_id/app_secret 换 `tenant_access_token`，缓存 + 过期刷新 | 基础设施 | **lark-cli 内置**（`lark-cli auth`，含 token 刷新） |
| 2 | **读表** `values` 接口 | 透传 | `lark-cli sheets +cells-get` |
| 3 | **写表**：把 `scopes=[...]`/`data=[...]` 逐格对齐、调飞书 `values_batch_update` | 透传 | `lark-cli sheets +cells-set --writes`（原生就是多区域批量） |
| 4 | **写图**：把图片 URL 变成飞书 image token 再写单元格 | 透传 | `lark-cli sheets +cells-set-image` / `+float-image-create` |
| 5 | 固定 token 鉴权 | 安全 | Function URL + 自定义 header 校验（或 IAM） |

### 1.3 **不在 n8n 里的逻辑**（重要，避免误判工作范围）

以下全部**已经在前端**，重写服务端**不需要**重新实现，但也**不能指望服务端补**：

- **字段映射**：`feishuService.ts` 的 `COLUMN_MAPPING`（Q/N/R/S/T/U/V）+ `constants.ts` 的 `SHEET_COLUMNS`（P/V/Y/AA/AB，**与前者冲突且疑似死代码**）。
- **数据清洗**：`formatDeliveryStatus()` / `generateTrackingText()` 把 `trackingDetails` 拼成 `date ; time - status - location ; ---` 文本。
- **行定位与去重**：`autoUpdateOrderToFeishu()` / `batchExportOrdersToFeishu()` 读 Q 列建 `orderId → rowNumber` 映射，命中则更新、未命中则追加到"最后一行+1"。
- **重试**：`apiClient.ts` 已实现指数退避（3 次，1s/2s/4s，仅重试 5xx/429）——**这一层换后端后完全保留，不用动**。
- **抓取**：Amazon/Walmart DOM 抓取、翻页、物流详情提取，全在前端。

> **关键判断**：n8n 工作流是**纯代理**，没有一行业务逻辑。所以"重新实现服务逻辑"的真实工作量远小于预期——**服务端约 300 行 Node**，风险点都在前端既有缺陷上（§6）。

---

## 2. lark CLI 可行性评估

### 2.1 实测验证结果（本机 `lark-cli` v1.0.90，真实执行，非文档推测）

| 能力 | 实测命令 / 证据 | 结论 |
|---|---|---|
| 读单元格 | `lark-cli sheets +cells-get --range ... --sheet-id/--sheet-name` | ✅ 有 |
| **多区域批量写** | `lark-cli sheets +cells-set --writes '[{sheet_name,range,cells},...]'`（最多 100 项，**单次批量请求**） | ✅ 直接对应 n8n 的 `scopes[]/data[][]` |
| **写图片到单元格** | `lark-cli sheets +cells-set-image --image <本地路径> --range T5` | ✅ 有 |
| 图片 token 复用 | `+cells-set` 的 `rich_text` 支持 `type="embed-image"` + `image_token` | ✅ 可从已有单元格取 token 复用 |
| 不落盘写图 | `rich_text.embed-image` 用 `image_uri`/`image_token`（**不需本地文件**） | ✅ **URL 图片可直写**，不必先下载 |
| 建表 | `lark-cli sheets +workbook-create` | ✅ 有 |
| 鉴权 | `lark-cli auth login`（Device Flow）/ `bot` 身份 / 157 个 scope 已授权 | ✅ 内置 token 管理 |
| 鉴权状态 | `lark-cli auth status` → `bot: ready`，`user: ready`（token valid） | ✅ 已可用 |

### 2.2 覆盖度结论（明确、不含糊）

- **可直接用 lark CLI 覆盖**：全部 4 个端点。鉴权、读表、写表、写图 **100% 覆盖**，无需手写任何飞书 OpenAPI 调用。
- **必须自建的部分**（约 300 行 Node，仅此而已）：
  1. HTTP 入口（把扩展的 4 个端点路由到 CLI 调用）；
  2. **CLI 进程调用封装**：`child_process.execFile` + 超时 + 非零退出码捕获 + JSON 解析；
  3. **`/update-data` 的入参转换**：`scopes[]/data[][]` → lark-cli `--writes` 结构（这是唯一有转换逻辑的地方）；
  4. **固定 token 换掉**：改用请求头密钥校验。
- **不需要自建的**：token 刷新（CLI 管）、定时任务（本插件无定时需求）、复杂清洗（已在前端）。

### 2.3 必须先解决的 3 个 lark-cli 落地问题（这是本方案真正的风险，不要被"可行"盖过）

| # | 问题 | 影响 | 处理方案 |
|---|---|---|---|
| **R1** | **CLI 是用户身份 OAuth，不是 bot 长期凭证** | `auth status` 显示 user token `expiresAt=2026-09-25T05:34`、`refreshExpiresAt=2026-10-02`。**Devic Flow 首次授权必须人工点浏览器**，之后靠 refresh token 续。refresh token 一旦过期（7 天窗口内需活跃续期），服务端会开始 401。 | Lambda 里用 **bot 身份 `--as bot`**（`auth status` 确认 `bot: ready`，bot 用 app_id/app_secret 自签，**不会过期**）；但**前提是这些表格必须把 bot 加为协作者**，否则权限不足。**这是上线前必须验证的第一件事。** |
| **R2** | **Lambda 里没有 lark-cli 二进制** | 依赖本机 `/opt/homebrew/bin/lark-cli` 会在 Lambda 上直接失败。 | 打包方案（择一）：① 用 **Lambda container image**，Dockerfile 里装 lark-cli（推荐，最简单）；② 若为 zip，需把 CLI 及其 Node runtime 一起塞进层。**container image 最省事**，代价是镜像约 100–200MB（不影响冷启动后的成本，只影响冷启动时间）。 |
| **R3** | **`+cells-set-image` 只吃本地图片路径** | n8n 版是**传 URL** 写图；而 CLI 该命令 `--image` 是本地路径。直接换算法不兼容。 | 两条路：① 走 `rich_text.embed-image` + `image_uri`（**URL 直写，推荐**，但需先确认 `image_uri` 接受外链而非仅飞书内部对象 ID——**待实测确认**）；② 退化为"Lambda 先下载图片到 `/tmp` 再调 `+cells-set-image`"（一定可行，代价是多一次下载和 `/tmp` 512MB 限制）。 |

> **诚实标注**：R1 / R3 是本方案唯一两个"必须上线前实测"的点，我**没有**在真实 Lambda 环境验证过。其余能力（读、批量写、建表、鉴权机制）已在本机 CLI 上确认存在。

---

## 3. 推荐架构

### 3.1 架构决策：为什么是 Lambda + Function URL

| 方案 | 月成本（估） | 常驻 | 适配度 | 结论 |
|---|---|---|---|---|
| **Lambda (arm64) + Function URL** | **$0.00–0.30** | 否 | 事件驱动、低频、突发批量；免费额度 100 万次/月 | ✅ **选它** |
| Lambda + API Gateway HTTP API | +$0 | 否 | 与上等价但多一跳、多一层配置；仅当需要自定义域名/限流才值 | 备选 |
| ECS Fargate（0.25vCPU/0.5GB，按需） | ~$9 | 否但有 20s+ 冷启 | 对本负载严重过度 | ❌ |
| EC2 t4g.nano 常驻 | ~$4.3（含 8GB gp3） | **是** | 为每天几次抓取养机器，纯浪费 | ❌ |
| 扩展直连飞书 OpenAPI | $0 | 否 | 需自己在扩展里做 token 管理 + app_secret 无处安放 | ❌ 不安全 |

**为什么 Function URL 而不是 API Gateway**：Function URL **不额外收费**且直接返回 JSON，省掉 API Gateway 的配置面和潜在费用。本场景无需网关能力。

### 3.2 架构图（文字描述）

```
┌─────────────────────────────────────────────────────────────┐
│ Chrome 扩展 (MV3)  background / sidepanel                    │
│  · 抓取 Amazon/Walmart 订单                                  │
│  · 字段映射 / 清洗 / 拼 trackingDetails 文本                  │
│  · 行定位与去重（读 Q 列 → orderId→rowNumber）                │
│  · apiClient 重试（3 次指数退避）—— 原样保留                  │
│  改动：n8nService.ts 的 baseUrl 一行                          │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTPS POST
                            │ x-api-key: <secret>   ← 取代明文 token
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ AWS Lambda  (arm64, 256MB, ~3s, container image)             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Node HTTP 入口（路由 4 个端点）                        │  │
│  │  /create-table        → lark-cli sheets +workbook-create│ │
│  │  /read-data           → lark-cli sheets +cells-get     │  │
│  │  /update-data         → lark-cli sheets +cells-set     │  │
│  │                        --writes (scopes→writes 转换)   │  │
│  │  /write-image-to-sheet→ lark-cli sheets +cells-set-image│ │
│  └───────────────────────┬───────────────────────────────┘  │
│  execFile('lark-cli', [...] with --as bot)                   │
└───────────┬─────────────────────────────┬───────────────────┘
            │                             │
            ▼                             ▼
┌───────────────────────┐   ┌─────────────────────────────────┐
│ Secrets Manager       │   │ lark-cli 内置鉴权                │
│ app_id/app_secret     │──▶│ tenant_access_token 换取 + 刷新  │
│ + 扩展侧 x-api-key     │   │ （无需自己写 token 管理）         │
└───────────────────────┘   └────────────┬────────────────────┘
                                          │
                                          ▼
                          ┌───────────────────────────────────┐
                          │ 飞书开放平台 Sheets OpenAPI        │
                          │ → 飞书在线表格（Amazon/Walmart 两张）│
                          └───────────────────────────────────┘

（可选）DynamoDB 按需表：存 scope→rowNumber 热缓存 / 调用审计
（可选）CloudWatch Logs：默认 7 天保留，控成本
```

### 3.3 与现有扩展的兼容策略

**保持 4 个端点契约不变**，扩展侧只改 `src/services/n8nService.ts` 的 `N8N_BASE_URL` 与 auth header。这样：
- 现有测试 `src/test/n8nService.spec.ts`、`feishuService.autoUpdate.test.ts` **不需要改**；
- 前端清洗/去重/重试逻辑**全部保留**，回滚成本 = 改回一行 URL。

---

## 4. 成本预估表

### 4.1 计价依据（**AWS 官方 Pricing API 实时抓取，us-east-1**）

| 项目 | 单价 | 来源 |
|---|---|---|
| Lambda 请求 | **$0.20 / 百万次** | AWSLambda offer file, `AWS-Lambda-Requests` |
| Lambda 时长 (arm64) | **$0.0000133334 / GB-s** | `AWS-Lambda-Duration-ARM` |
| Lambda 时长 (x86) | $0.0000166667 / GB-s | `AWS-Lambda-Duration` |
| DynamoDB 写 (按需) | **$0.625 / 百万 WRU** | AmazonDynamoDB `WriteRequestUnits` |
| DynamoDB 读 (按需) | **$0.125 / 百万 RRU** | `ReadRequestUnits` |
| Secrets Manager | **$0.40 / 密钥 / 月** + $5/百万次调用 | AWSSecretsManager |
| CloudWatch Logs 摄入 | $0.50 / GB | AmazonCloudWatch `DataProcessing-Bytes` |

### 4.2 量级假设（基于插件实际使用形态）

| 参数 | 取值 | 依据 |
|---|---|---|
| 单次全量导出 | ~50–200 单 | 一次抓取的典型订单量 |
| 导出频次 | 5–20 次/月 | 手动触发为主，非定时 |
| 每单 API 调用 | ~3 次（读 Q 列 1 + 批量写 1 + 图片 ~1） | `batchExportOrdersToFeishu` 已合并为批量写 |
| 图片 | 约 10% 订单有配送图 | `deliveryPhotoUrl` |
| 月请求数 | **~1,500–12,000 次** | 上限 |
| 内存 / 时长 | 256MB / ~3s（含 CLI 冷启内） | CLI 进程开销 |

### 4.3 成本表

| 组件 | 配置 | 月请求 | 计算 | 月成本 |
|---|---|---|---|---|
| Lambda 请求 | arm64 | 12,000 | 12,000 × $0.20/1e6 = $0.0024；**免费额度 100 万次/月** | **$0.00** |
| Lambda 时长 | 256MB, 3s | 12,000 | 12,000 × 3s × 0.25GB = 9,000 GB-s；× $0.0000133 = $0.12；**免费额度 400,000 GB-s/月** | **$0.00** |
| Function URL | — | — | 无额外费用 | **$0.00** |
| DynamoDB（可选） | 按需 | 12,000 写 | 12,000 × $0.625/1e6 = $0.0075 | **$0.00** |
| CloudWatch Logs | 7 天保留 | ~50MB | 超出 5GB 免费额度为 0 | **$0.00** |
| Secrets Manager | 1 个密钥 | — | $0.40/月 | **$0.40** |
| **合计（含 Secrets Manager）** | | | | **$0.40 / 月** |
| **合计（用 Lambda 加密环境变量替代）** | | | | **$0.00 / 月** |

### 4.4 成本结论（具体数字区间）

- **稳态：$0.00 / 月**（全部落在免费额度内）。
- **若用 Secrets Manager 存凭证：$0.40–0.45 / 月**（几乎全是那 $0.40 的密钥月费）。
- **悲观上限**（月 10 万次请求、每次 3s / 256MB）：请求 $0.02 + 时长 $1.00 + 密钥 $0.40 ≈ **$1.42 / 月**，仍然可忽略。
- **对比**：旧 n8n 需要一台常驻实例（按 t4g.nano 同类规格折算 ≈ **$4.3/月**，若原 n8n 跑在更大机器或托管服务上则 10–50 倍于此）。**本方案把这项固定成本清零。**

> **省钱建议**：$0.40 的密钥月费在此量级下占了成本的 100%。把 `app_id/app_secret` 放进 **Lambda 加密环境变量**（KMS 默认密钥不额外收费）即可再省 $0.40 → **$0.00/月**。Secrets Manager 的自动轮换在本场景**没有必要**。

---

## 5. 分步落地计划

### Milestone 1 — 打通"CLI 能替代 n8n"的可行性（0.5–1 天，**不写生产代码**）

> 目标：用一条命令证明 R1/R3 两个风险点是否成立。**这步不做完，后面全是空谈。**

1. 拿一张测试表，执行 `lark-cli sheets +cells-set --as bot --url <测试表URL> --sheet-name Sheet1 --range A1 --cells '[[{"value":"probe"}]]'`。
   - **通过条件**：bot 写入成功 → R1 解决，服务端可永久免人工授权。
   - **失败**：把 bot 加为表格协作者后重试；仍失败则改为 user 身份 + refresh token 续期方案（需加"续期失败告警"）。
2. 测图片 URL 直写：构造 `rich_text.embed-image` + `image_uri` 写一格外链图。
   - **通过** → 用 `+cells-set`，无需下载。**失败** → 走 `/tmp` 下载 + `+cells-set-image`。
3. 用 `--dry-run` 抓取真实请求体，确认 `--writes` 结构与 `scopes[]/data[][]` 的转换规则。

**交付**：一份 3 条命令的验证记录（含真实输出）。

### Milestone 2 — Lambda 服务 + 部署（2–3 天）

1. 新建 `server-lambda/`（**不要复用旧的 `server/`**，那是已退役的 Azure Functions）：
   - `handler.ts`：4 个路由 + header 密钥校验 + 统一 `{success, data}` 响应格式（**必须与扩展 `apiClient.ts` 期望的 `success/data` 包裹一致**）。
   - `larkCli.ts`：`execFile` 封装（超时 15s、非零退出码→ 抛错、stdout JSON 解析、`--as bot`）。
   - `toWrites(scopes, data)`：`Q2` → `{sheet_name, range:"Q2", cells:[[{value}]]}` 的转换 + 单请求 ≤100 项的**分批**。
2. `Dockerfile`（container image，内装 lark-cli）+ SAM `template.yaml`：
   - arm64 / 256MB / 超时 30s / `ReservedConcurrency` **不设**（冷启动可接受，避免浪费）。
   - Function URL，`AuthType: NONE` + 自定义 `x-api-key` 校验（或 `AWS_IAM`，但扩展签名复杂，不推荐）。
3. `sam deploy`，拿到 Function URL。

**交付**：可用的 Function URL + 部署脚本 + README。

### Milestone 3 — 扩展切换 + 前端缺陷修复（1–2 天）

1. 改 `n8nService.ts`：`N8N_BASE_URL` → Function URL；`N8N_AUTH_TOKEN` → 新密钥（**改从 `chrome.storage` 读，不再硬编码**）。
2. **修 §6 的 3 个缺陷**（否则换后端也写不对表）。
3. `pnpm test` + 手动跑一次 Amazon 与 Walmart 全流程。
4. 保留回滚：旧 URL 只在一个常量里，一行可切回。

**交付**：`dist.crx` 更新 + 端到端验证记录。

### Milestone 4（可选）— 减法与加固

- 删除死代码 `constants.ts:SHEET_COLUMNS`（与 `COLUMN_MAPPING` 冲突）。
- 删除已退役的 `server/`（Azure）目录，避免后人误用。
- CloudWatch 告警：Lambda 错误率 > 5% 时告警（$0.10/月/告警，可接受）。
- 加 `sourceIp` 之外的限流（本场景可省，低频）。

---

## 6. 换后端**之前**必须先修的前端缺陷（否则白干）

这些是本次阅读源码发现的真实问题，**与 n8n 下线无关**，但会直接让"换完后端"依然失败：

| # | 位置 | 问题 | 后果 |
|---|---|---|---|
| **D1** | `src/services/feishuService.ts` `batchExportOrdersToFeishu` | 传入 `availableOrders` 时，用**数组下标** `i+2` 当行号，不做任何校验 | 该顺序来自 Walmart 表格 `!P:Q` 读取结果；**一旦表格被排序/过滤/有空行，行号整体错位 → 写串行**。应改为按订单号真实匹配，或读回确认。 |
| **D2** | `src/manifest.json` | 缺 `host_permissions`（旧分析报告 §0 已记录），且现在要访问 **Function URL 的新域名** | 扩展请求可能被 CORS/权限拦截。需加 `host_permissions` 为 Function URL 域名。 |
| **D3** | `src/config/constants.ts` `SHEET_COLUMNS` | 列映射为 `P/V/Y/AA/AB`，与 `feishuService.ts` 实际使用的 `COLUMN_MAPPING` `Q/N/R/S/T/U/V` **完全冲突** | 若被任何代码路径引用会造成错列写入；当前 grep 显示**仅定义未被引用**，判定为死代码 → 应删除以防误用。 |

> **说明**：D1 是最危险的一条。`batchExportOrdersToFeishu` 的"成功计数"也是估算（`orders.filter(orderId).length - failCount`），并非 API 真实回执——换后端后建议顺带改成读取 `updatedCells` 校验。

---

## 7. 风险与未验证项（明确清单）

| 级别 | 项 | 状态 | 缓解 |
|---|---|---|---|
| 🔴 高 | **R1 bot 身份能否写目标表格**（权限/协作者） | **未验证·必须先测** | M1 第 1 步；失败则退回 user refresh token + 续期告警 |
| 🔴 高 | **R2 lark-cli 在 Lambda 内可用性** | 未验证（本机可用） | container image 打包；M1 后本地 `docker run` 验证 |
| 🟡 中 | **R3 图片 URL 直写** | 未验证 | M1 第 2 步；退化方案已备（下载到 `/tmp` + `+cells-set-image`） |
| 🟡 中 | D1 行号错位 | **已确认（源码级）** | M3 修复 |
| 🟡 中 | `--writes` 单请求 100 项上限 | 文档明确 | 服务端分批 |
| 🟢 低 | CLI 冷启动延迟（镜像较大） | 预期 | 低频场景可接受；必要时加 provisioned concurrency（**不要**，会引入固定成本） |
| 🟢 低 | Lambda `/tmp` 512MB 限制 | 已知 | 仅写图退化路径用到；单图足够 |
| 🟢 低 | `--as bot` 时部分 scope 可能缺失 | 未知 | `lark-cli auth check` 验证；必要时调整应用权限 |

---

## 8. 附：证据与复现方式

- **lark-cli 能力**：`lark-cli sheets --help`、`lark-cli sheets +cells-set --help`、`lark-cli sheets +cells-set-image --help`、`lark-cli sheets +cells-set --flag-name cells --print-schema`、`lark-cli auth status`、`lark-cli doctor`（本机 v1.0.90 实跑）。
- **AWS 价格**：`https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{AWSLambda,AmazonDynamoDB,AWSSecretsManager,AmazonCloudWatch}/current/index.json`（us-east-1，`OnDemand` 条目）。
- **扩展契约**：`src/services/n8nService.ts`、`src/services/feishuService.ts`、`src/config/constants.ts`、`src/core/apiClient.ts`、`src/services/walmartScraping.ts`、`src/components/sidepanel/Layout.tsx`。
- **补充**：仓库根 `ORDER_ANALYSIS.md` 已对本插件做过整体分析（含 n8n/Azure 现状与入口文件清单），可与本报告 §1 交叉验证。

> **关于代码改动**：本轮为分析 + 方案，**未修改任何源码**（题目明确"本轮不要求直接改代码"）。
