# Track 5: Settings UI 增强

> 状态：⬜ 待认领 · 优先级：P1 · 前置依赖：Track 1 已合并

## 目标

补齐 Settings 缺失的 Tab：Fast Rules、Tool Tiers、Knowledge Validate、飞书 deps 轮询。

## 独占文件清单（只能改这些）

- `app/android/app/src/main/kotlin/com/ethan/agent/ui/settings/SettingsScreen.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/settings/SettingsViewModel.kt`

**严禁触碰**：
- `data/EthanRepository.kt`、`core/model/`（Track 1 管）
- `ui/components/`（Track 7 管）
- `ui/theme/`（Track 7 管，主题切换由 Track 7 实现，Settings 只是入口）
- 其他 UI 模块

## 当前实现

SettingsScreen 已有 11 个 Tab：Connection / General / Providers / Channels / Identity / Soul / Tools / Heartbeat / Profile / PromptPreview / ApiKeys

**缺失**：
- ❌ Fast Rules 快捷路由规则
- ❌ Tool Tiers 路由档位
- ❌ Knowledge 知识库连通性验证
- ❌ 飞书依赖状态轮询

## 缺失功能（本 Track 任务）

### 1. 新增 Tab：Fast Rules（P0）

后端：
- `GET /api/fast-rules`（Track 1 已加）
- `GET /api/fast-rules/options`
- `PATCH /api/fast-rules`

需求：
- 新增 Tab `FastRules("Fast Rules")`
- 显示当前 `fast_base_tools` 列表（已挂载的快速工具）
- 显示 `fast_rules` 规则列表
- 提供「添加规则」入口：从 `fetchFastRuleOptions` 返回的可挂载工具 + 已安装技能中选
- 编辑后调 `updateFastRules`

参考：[desktop/src/components/SettingsView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/SettingsView.tsx) 中 fast-rules Tab

### 2. 新增 Tab：Tool Tiers（P1）

后端：`GET /api/tool-tiers`（Track 1 已加）

需求：
- 新增 Tab `ToolTiers("路由档位")`（或合并到 FastRules 下作为子节）
- 显示两档：
  - Fast：快速档位包含的工具列表
  - Full：完整档位包含的工具列表
- 每个工具显示 name、description、tier
- 只读，不需要编辑（实时计算）

参考：[desktop/src/components/ToolTiersView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/ToolTiersView.tsx)

### 3. Knowledge 连通性验证（P1）

后端：`POST /api/settings/knowledge/validate`（Track 1 已加）

需求：
- 在现有 Channels Tab 后面（或 General Tab 末尾）加「知识库验证」入口
- 弹出 BottomSheet：
  - 选择 backend type：filesystem / obsidian / external
  - 根据 type 显示对应配置字段（path / vault / endpoint）
  - 「测试连接」按钮调 `validateKnowledge`
  - 返回结果用 snackbar 展示（成功/失败 + 详情）

### 4. 飞书依赖状态轮询（P1）

后端：
- `GET /api/channels/lark/deps-status`（Track 1 已加）
- `POST /api/channels/lark/install-deps`

需求：
- 在现有 Channels Tab 中，飞书渠道下方加「依赖状态」区域
- 显示当前安装状态（installing / installed / failed / unknown）
- 安装中时每 2s 轮询
- 未安装时显示「安装依赖」按钮，点击调 `installLarkDeps`
- 安装完成后停止轮询

参考：[desktop/src/lib/api-misc.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-misc.ts) 中 `fetchLarkDepsStatus`、`installLarkDeps`

### 5. 主题切换入口（P0，仅入口）

> 实际主题系统由 Track 7 实现，本 Track 只在 Settings 中加入口

需求：
- 在 General Tab 加「主题」选项：
  - 跟随系统（默认）
  - 浅色
  - 深色
  - 青瓦 / 暖橙 / 素纸 / 微雾（5 主题，来自 Web）
- 选择后调用 Track 7 提供的主题切换接口（约定：通过 `EthanRepository.setTheme(themeId: String)` 切换；Track 7 负责实现 Repository 方法和 DataStore 持久化）
- 如果 Track 7 尚未合并，先用 `TODO("Track 7")` 占位，不要阻塞本 Track

## Tab 设计建议

更新 `SettingsTab` 枚举：

```kotlin
enum class SettingsTab(val title: String) {
    Connection("连接"),
    General("通用"),
    Providers("模型"),
    Channels("渠道"),
    Identity("身份"),
    Soul("灵魂"),
    Tools("工具"),
    Heartbeat("心跳"),
    Profile("画像"),
    PromptPreview("预览"),
    ApiKeys("Keys"),
    FastRules("Fast Rules"),       // 新增
    ToolTiers("路由档位"),          // 新增
}
```

## 参考代码

- 后端：[ethan/interface/routers/settings.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/settings.py)
- Web 客户端：[desktop/src/lib/api-settings.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-settings.ts)、[api-misc.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-misc.ts)
- Web 视图：[desktop/src/components/SettingsView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/SettingsView.tsx)

## 验收标准

- [ ] Fast Rules Tab 能加载并显示当前规则
- [ ] Tool Tiers Tab 能加载并显示两档工具列表
- [ ] Channels Tab 中能验证知识库连通性
- [ ] Channels Tab 中能查看飞书依赖状态、能触发安装
- [ ] General Tab 中能切换主题（即使 Track 7 未合并也要有入口）
- [ ] 编译通过、lint 无 error

## 不要做的事

- ❌ 不要改 `EthanRepository`（Track 1 管）
- ❌ 不要实现主题系统本身（Track 7 管）
- ❌ 不要改 `ui/theme/`（Track 7 管）
- ❌ 不要破坏现有 11 个 Tab 的功能
