# Ethan Android App — 产品需求文档 (PRD)

> 版本: 1.0.0 · 包名: `com.ethan.agent` · 最低 SDK: 26 · 目标 SDK: 35

## 1. 产品定位

Ethan Android 是 [Ethan Agent](https://github.com/ethan-agent/ethan-agent) 的移动端客户端，对接自托管 Python 后端（FastAPI，默认 `:8900`）。与 Web UI 共享同一套 `/api/*` REST + SSE 接口，在手机上提供更自然的触控交互。

### 1.1 设计原则（相对 Web 的改进）

| 维度 | Web | Android App |
|------|-----|-------------|
| 导航 | 左侧边栏 + 多页面跳转 | 底部 Tab（对话/全部/更多/设置）+ 手势返回 |
| 聊天输入 | 桌面键盘 + 悬停引用 | 底部固定输入栏、长按消息引用、系统文件选择器附件 |
| 会话列表 | 侧边栏 + 独立页面 | 独立「全部对话」页 + 3 秒轮询刷新 |
| 记忆/知识库 | 双栏桌面布局 | 主从分栏（平板友好），单列列表（手机） |
| 配置 | 多 Tab 设置页 | **连接配置**独立 Tab，登录页即可配服务器 |
| 授权弹窗 | 模态对话框 | 原生 AlertDialog，不阻塞系统返回 |
| 文档 | 独立路由（无侧边栏） | 「更多」入口，Markdown 阅读 |

### 1.2 每个页面的验收标准（改完必须按此自评）

**流程（不可跳过）**：每改完一个页面 → `assembleDebug` → `adb install` → 真机截图 → 按下面两张清单自评 → 有问题就继续改，直到达标。

**A. 审美标准**

- [ ] **不空**：内容区不要出现大段死白。列表项少时也要有合理布局（时间轴撑满、空状态有说明），不能让人以为页面坏了。
- [ ] **不挤**：顶栏标题与实际操作按钮不重叠；360dp 宽的手机上标题完整可见。
- [ ] **有层级**：标题/正文/辅助文字字号与颜色分明，不是一片平铺。
- [ ] **对齐**：左右边距统一（列表 12dp 起）；同一行的元素基线对齐。
- [ ] **卡片不虚高**：内部没有大片无意义留白；操作区与内容区比例合理。
- [ ] **颜色克制**：层级靠 surface 色阶 + 发丝边（`outlineVariant`）区分，不靠彩色描边。

**B. 交互标准（同样重要，不能只看好看）**

- [ ] **拇指可达**：高频操作用户单手能够到（屏幕下半/边缘）；不要把所有操作都堆在顶部。
- [ ] **点击目标 ≥ 48dp**：图标按钮不能小于 `IconButton` 默认尺寸，密集排布时也要保证可点。
- [ ] **危险操作有确认**：删除等破坏性操作必须二次确认，且按钮不能与普通操作紧邻（防误触）。
- [ ] **可点的地方要有反馈**：能点的卡片/行应该有水波纹或明确按压态。
- [ ] **状态一眼可辨**：运行中/暂停等状态要有明显视觉区分，不靠读文字。
- [ ] **无 hover 假设**：Web 上靠 `group-hover` 才出现的操作，Android 必须常驻显示。
- [ ] **空状态有指引**：空列表要说明原因（如「今天和明天暂无定时任务」），而不是一片空白。

**C. Edge-to-edge（对齐 Gmail 的做法）**

- [ ] 顶栏背景色**延伸到状态栏底下**，与状态栏区域连成一片，不出现独立色带。
- [ ] 顶栏内容（标题/图标）留出状态栏高度的内边距，**不被状态栏遮挡**。
- [ ] 不要用 `statusBarsPadding()` 让开状态栏 —— 那会在顶栏上方留出一条空白/异色带。
- [ ] 内容上边缘到状态栏的距离应当**可控且紧凑**，不要显得太空。

---

## 2. 功能清单与实现细节

### 2.1 登录与连接配置 【P0 · 已实现】

**用户故事**：作为用户，我希望在手机上配置 Ethan 服务器地址和 Token，以便连接自托管 Agent。

| 步骤 | 行为 | API |
|------|------|-----|
| 1 | 启动 App，读取 DataStore 中已保存的 serverUrl + token | — |
| 2 | 若有 token，自动 `POST /api/auth` 验证 | `POST /api/auth` |
| 3 | 验证失败 → 显示登录页 | — |
| 4 | 用户填写服务器地址（如 `http://192.168.1.100:8900`） | `GET /api/health`（可选，显示版本） |
| 5 | 用户填写 Access Token，点击登录 | `POST /api/auth` |
| 6 | 成功 → 持久化 token，进入主界面 | DataStore |

**需配置项**：
- `serverUrl`：后端根地址，App 自动追加 `/api`
- `authToken`：对应 `~/.ethan/config.yaml` 中 `network.auth_token` 或 `users[].web_token`

---

### 2.2 聊天（核心）【P0 · 已实现】

**用户故事**：作为用户，我希望在手机上与 Agent 流式对话，看到工具调用过程，并在敏感操作时授权。

| 步骤 | 行为 | API |
|------|------|-----|
| 1 | 进入对话页，加载模型列表和对话模式 | `GET /api/models`, `GET /api/modes` |
| 2 | 选择模型（下拉）和模式（FilterChip，如「苏念·陪伴倾听」） | — |
| 3 | 输入消息；若无 session 先创建 | `POST /api/sessions?model=&mode=` |
| 4 | 发送消息，SSE 流式接收；生成中发送改为**排队**（队列 chips 可移除/取回编辑，本轮跑完自动按序发出） | `POST /api/chat` (stream=true) |
| 5 | 解析 SSE 事件：`content` 增量、`tool` 状态、`consent_request`、`done`+`usage`；工具结束时清空正文、旧文本进步骤 thought（对齐 web 的替换语义） | — |
| 6 | 收到授权请求 → 弹窗 Allow/Deny | `POST /api/consent/{id}` |
| 7 | 长按消息 → 设置引用，下次发送带 `quote` | — |
| 8 | 附件按钮 → 系统文件选择器 → 上传 | `POST /api/upload` |
| 9 | 首次使用显示 Onboarding 横幅 | `GET/POST /api/onboarding/*` |
| 10 | 生成中「补充信息」独立入口：立即注入当前 run（无活跃 run 时 409 自动降级普通发送） | `POST /api/chat/{id}/inject` |
| 11 | 输入框展开全屏编辑（长文本写完再发）；双击气泡进阅读模式，返回键只退阅读不退会话 | — |

**Slash 命令（客户端拦截）**：
- `/new` — 新建对话
- `/compact` — 压缩当前会话历史
- `/sessions` — 列出最近 8 条会话
- `/help` — 显示帮助

**SSE 事件类型**：
```
content          → 文本增量
tool + state     → 工具时间线 (start/done/error)
consent_request  → 授权弹窗
done + usage     → 完成，显示 token 用量
error            → 错误提示
```

---

### 2.3 全部对话 【P0 · 已实现】

| 步骤 | 行为 | API |
|------|------|-----|
| 1 | 展示会话卡片列表（标题、摘要、模型、来源、时间），顶部排他类别筛选：全部对话 / 定时任务对话 / 心跳对话（默认排除定时、心跳、后台任务会话，与 web 同口径） | `GET /api/sessions`（`hide_heartbeat` / `hide_scheduled` / `hide_background` / `title_prefixes`） |
| 2 | 搜索框 300ms debounce（与类别筛选 AND 合成） | `GET /api/sessions?q=` |
| 3 | 后台每 3 秒轮询（搜索时暂停；类别视图下轮询不回灌，防冲掉专属列表） | `GET /api/poll` |
| 4 | 点击卡片 → 跳转对应对话 | — |
| 5 | 重命名 / 删除 | `PATCH/DELETE /api/sessions/{id}` |

**来源标签**：web · lark · repl · heartbeat

---

### 2.4 记忆 【P1 · 已实现】

三 Tab 管理 Agent 长期记忆：

| Tab | 功能 | API |
|-----|------|-----|
| 事实 Facts | 列表 + 选中编辑 + 删除 | `GET/PATCH/DELETE /api/memory/facts/*` |
| 流程 Procedures | 列表 + 删除 | `GET/DELETE /api/memory/procedures/*` |

---

### 2.5 知识库 【P1 · 已实现】

| 步骤 | 行为 | API |
|------|------|-----|
| 1 | 左列表 + 右编辑区 | `GET /api/knowledge` |
| 2 | 搜索（关键词/语义切换） | `GET /api/knowledge/search` |
| 3 | 新建 / 编辑 / 删除 | `POST/PUT/DELETE /api/knowledge/*` |

---

### 2.6 技能 【P1 · 已实现】

| 步骤 | 行为 | API |
|------|------|-----|
| 1 | 左列表展示所有 Skill | `GET /api/skills` |
| 2 | 选中查看/编辑（name 创建后不可改） | `GET/POST /api/skills/{name}` |
| 3 | 删除 | `DELETE /api/skills/{name}` |

---

### 2.7 定时任务 【P1 · 已实现】

| 步骤 | 行为 | API |
|------|------|-----|
| 1 | 展示 cron/interval 任务卡片 | `GET /api/schedule` |
| 2 | 暂停/恢复 | `PATCH /api/schedule/{id}` |
| 3 | 删除 | `DELETE /api/schedule/{id}` |
| 4 | 查看关联对话 | 跳转 `/chat/{session_id}` |

> 注意：定时任务**创建**仅通过 Agent 对话中的 schedule 工具，App 不提供创建表单（与 Web 一致）。

---

### 2.8 设置 【P1 · 已实现】

| Tab | 内容 | API |
|-----|------|-----|
| 连接 | 服务器地址、版本检测 | DataStore + `GET /api/health` |
| 通用 | agent_name, default_model, lite_model, language, heartbeat | `GET/PATCH /api/settings/agent` |
| 模型 | Provider api_key / base_url | `GET/PATCH /api/settings/providers` |
| 渠道 | 飞书 app_id / app_secret | `GET/PATCH /api/channels` |
| 身份/灵魂/工具/心跳 | 系统 Prompt Markdown 文件 | `GET/PATCH /api/settings/system` |
| 画像 | 用户 Profile 编辑 | `GET/PATCH /api/settings/profile` |
| 预览 | System Prompt 预览 | `GET /api/system-prompt-preview` |
| Keys | API Key 管理 | `GET/POST/DELETE /api/api-keys/*` |

---

### 2.9 文档 【P2 · 已实现】

| 步骤 | 行为 | API |
|------|------|-----|
| 1 | 文档列表 | `GET /api/docs` |
| 2 | 点击阅读 Markdown 内容 | `GET /api/docs/{slug}` |

---

### 2.10 日志 【P2 · 已实现】

Web 有 `LogsView` 组件但未挂载路由；Android 在「更多」中提供：

| 步骤 | 行为 | API |
|------|------|-----|
| 1 | 切换 backend/frontend 日志 | `GET /api/logs?type=&lines=500&q=` |
| 2 | 关键字过滤 + 刷新 | — |

---

## 3. 工程架构

```
app/android/
├── app/                    # 应用层：UI、ViewModel、Repository、DI
├── core/
│   ├── model/              # kotlinx.serialization 数据模型
│   ├── network/            # Retrofit API + SSE 客户端
│   └── datastore/          # DataStore 偏好设置
├── gradle/libs.versions.toml
└── PRD.md
```

**技术栈**：
- Kotlin 2.1 + Jetpack Compose + Material 3
- Hilt 依赖注入
- Retrofit + OkHttp（REST + SSE）
- DataStore Preferences（配置持久化）
- Navigation Compose（单 Activity 多页面）
- minSdk 26 / compileSdk 35 / targetSdk 35

---

## 4. 配置清单（部署前必读）

### 4.1 服务端（首次部署）

| 配置项 | 位置 | 说明 |
|--------|------|------|
| LLM API Key | `.env` 或 `config.yaml` providers | Anthropic/OpenAI/GLM 等 |
| `network.auth_token` | `~/.ethan/config.yaml` | Web/App 登录 Token |
| `ethan serve` | 终端 | 启动 API 服务（:8900） |
| 防火墙 | NAS/路由器 | 确保手机能访问 8900 端口 |

### 4.2 客户端（App 内配置）

| 配置项 | 入口 | 说明 |
|--------|------|------|
| 服务器地址 | 登录页 / 设置→连接 | 如 `http://NAS_IP:8900` |
| Access Token | 登录页 | 与服务端 auth_token 一致 |
| 主题 | 跟随系统（可扩展） | 与 Web/Desktop 共享同一套 5 套主题：青瓦（默认）/ 暖橙 / 素纸 / 微雾 / 深色（见 `web/components/chat/themes.ts`） |

### 4.3 可选配置

| 配置项 | 说明 |
|--------|------|
| 飞书渠道 | 设置→渠道，填 app_id + app_secret |
| 多用户 | 服务端 `users[].web_token`，每用户独立数据 |
| HTTPS | 生产环境建议反向代理 + 证书；开发可用 HTTP（已配置 cleartext） |

---

## 5. 未实现 / 后续迭代

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 推送通知 | P2 | 定时任务完成、心跳结果通知 |
| 离线缓存 | P2 | 会话/消息本地 Room 缓存 |
| 生物识别锁 | P2 | 保护 Token |
| 平板双栏布局 | P2 | 聊天 + 会话列表同屏 |
| 模型发现/添加 | P3 | Web General 中的 discover models |
| iOS 版本 | P3 | 共享 core 模块或 KMP |

---

## 6. 构建与运行

```bash
cd app/android
export ANDROID_HOME=~/Library/Android/sdk
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

在 Android Studio 中打开 `app/android` 目录即可调试。

---

## 7. API 参考

完整 OpenAPI 文档：`http://<server>:8900/api/swagger`

Android 与 Web 共用 `web/lib/api.ts` 中定义的全部 `/api/*` 端点，鉴权方式为 `Authorization: Bearer <token>`。
