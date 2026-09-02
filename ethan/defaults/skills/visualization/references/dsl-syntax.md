# Excalidraw DSL 语法参考

本文件是 `excalidraw` 技能的 DSL 快速模式参考。DSL 适合 ≤15 节点的简单流程图；
复杂图请回 SKILL.md 走 JSON 模式。

DSL 通过 `npx @swiftlysingh/excalidraw-cli create --inline "..."` 解析为标准 `.excalidraw` 文件。
> 注：DSL 模式产物是 `.excalidraw`（纯 JSON），不是 Obsidian `.md`。需要 Obsidian 直接打开时，
> 用 SKILL.md 中的 JSON 模式生成 `.md`，或把 DSL 产物导入 excalidraw.com 微调后导出再放进 vault。

## 1. 节点元素（形状由括号类型决定）

| 语法 | 形状 | 语义建议 |
|------|------|----------|
| `[步骤名]` | 矩形 | 过程 / 动作 / 步骤 |
| `{决策?}` | 菱形 | 判断 / 条件分支（建议以 `?` 结尾） |
| `(起止)` | 椭圆 | 开始 / 结束 / 终态 |
| `((同心圆))` | 双圆 | 关键终点 / 流程终结 |
| `[[存储]]` | 数据库（圆柱） | 数据存储 / 持久化 |
| `((云))` 或 `[/云/]` | 云形 | 外部系统 / 抽象状态 |
| `>子例程<` | 子流程框 | 调用另一张图 / 子流程 |
| `"纯文本"` | 无形状文本 | 标签 / 注释 / 自由文本 |

约定：
- 起止节点建议命名 `(Start)` / `(End)`，决策节点建议以 `?` 结尾。
- 节点名含空格或特殊字符时，整体放在括号内即可，无需额外引号。

## 2. 连接关系

| 语法 | 含义 |
|------|------|
| `->` | 实线箭头（默认） |
| `-->` | 虚线箭头（异步 / 可选 / 弱依赖） |
| `-=>` | 粗箭头（强依赖 / 主路径） |
| `-.->` | 点线箭头（事件 / 通知） |
| `-> "标签" ->` | 带标签的箭头（标签会渲染在连线中点） |
| `--` | 无箭头连线（仅关联） |
| `<->` | 双向箭头（双向交互） |

多标签写法：`{OK?} -> "是" -> [保存]`，`{OK?} -> "否" -> [重试]`。

## 3. 布局指令（行首以 `@` 开头）

| 指令 | 含义 | 默认 |
|------|------|------|
| `@direction TB` | 流向从上到下 (Top→Bottom) | 是 |
| `@direction LR` | 流向从左到右 (Left→Right) | — |
| `@direction BT` | 流向从下到上 | — |
| `@direction RL` | 流向从右到左 | — |
| `@spacing 60` | 节点间距（像素） | 40 |
| `@bgcolor #f5f5f5` | 画布背景色 | `#ffffff` |
| `@title 图标题` | 自动添加标题文本 | — |

布局指令必须单独成行，放在 DSL 开头（在第一个节点之前）。

## 4. 子图与分组

```
@subgraph 前端层
  (UI) -> [API Client]
@end

@subgraph 后端层
  [API Client] -> [Service]
  [Service] -> [[DB]]
@end
```

- `@subgraph <名称>` ... `@end`：把一组节点圈在一个半透明分组里，便于表达层次。
- 子图可嵌套，但建议不超过 2 层。
- 跨子图连线自动穿透分组边界。

## 5. 注释

```
# 这是单行注释，不会被渲染
(Start) -> [Step 1]  # 行尾注释也允许
```

## 6. 完整示例

### 示例 1：登录流程（含决策与重试）
```text
@direction TB
@spacing 50
@title 用户登录流程

(Start) -> [输入账号密码] -> [提交表单] -> {验证成功?}
{验证成功?} -> "是" -> [生成 Token] -> [写入 Session] -> (End)
{验证成功?} -> "否" -> {重试次数 < 3?}
{重试次数 < 3?} -> "是" -> [提示错误] -> [输入账号密码]
{重试次数 < 3?} -> "否" -> [锁定账号] -> (End)
```

### 示例 2：微服务架构（LR + 子图）
```text
@direction LR
@spacing 60

@subgraph 客户端
  (Web)
  (Mobile)
@end

@subgraph 网关层
  [[API Gateway]]
@end

@subgraph 服务层
  [User Service]
  [Order Service]
  [Payment Service]
@end

@subgraph 存储层
  [[User DB]]
  [[Order DB]]
  [[Payment DB]]
@end

(Web) -> [[API Gateway]]
(Mobile) -> [[API Gateway]]
[[API Gateway]] -> [User Service]
[[API Gateway]] -> [Order Service]
[[API Gateway]] -> [Payment Service]
[User Service] -> [[User DB]]
[Order Service] -> [[Order DB]]
[Payment Service] -> [[Payment DB]]
```

### 示例 3：决策树（带虚线可选路径）
```text
@direction TB

(Start) -> [加载数据] -> {数据有效?}
{数据有效?} -> "是" -> [预处理] -> [训练模型] -> (End)
{数据有效?} -> "否" --> [记录错误日志] --> [通知运维] --> (End)
```

## 7. DSL → Obsidian 工作流

DSL 模式产物是 `.excalidraw`，要塞进 Obsidian vault 有两条路径：

**路径 A（推荐，最简单）：DSL 仅起草，最终走 JSON 模式**
1. 用 DSL 快速验证流程逻辑是否正确（输出 `.excalidraw` 临时文件）。
2. 在 excalidraw.com 打开微调布局。
3. 把最终 JSON 抽出，按 SKILL.md「Obsidian 模式 `.md` 文件结构」包成 `.md` 写入 vault。

**路径 B（适合懒人）：直接把 `.excalidraw` 放进 vault**
1. DSL 输出 `.excalidraw` 文件，`cp` 到 vault 的 `Excalidraw/` 子目录。
2. Obsidian Excalidraw 插件支持直接识别 `.excalidraw` 扩展名（需在插件设置中开启）。
3. 但会失去 Markdown 双向链接与 frontmatter tags 的好处，**不推荐作为主路径**。

## 8. 备选：DOT / Graphviz 语法

CLI 也支持 DOT 语法（适合已经熟悉 Graphviz 的用户）：

```bash
npx @swiftlysingh/excalidraw-cli create --dot --inline '
digraph G {
  rankdir=LR;
  A [shape=box]; B [shape=diamond];
  A -> B [label="next"];
}
' -o output.excalidraw
```

执行 `npx @swiftlysingh/excalidraw-cli --help` 查看所有参数（包括 `--theme`、`--font-family` 等）。

## 9. 限制与降级

| 场景 | DSL 表现 | 建议 |
|------|----------|------|
| ≤15 节点的线性/分支流程 | ✅ 完美 | 直接用 DSL |
| 16-30 节点 | ⚠️ 布局可能拥挤 | DSL 起草后微调，或改 JSON |
| >30 节点 | ❌ 自动布局难以收敛 | 必须走 JSON 模式分节生成 |
| 需要嵌入真实代码/JSON 证据 | ❌ DSL 不支持 | 走 JSON 模式 |
| 需要动画顺序 | ❌ DSL 不支持 | 走 JSON Animated 模式 |
| 需要自定义配色 / 字体 | ⚠️ 仅能通过 CLI 参数 | 走 JSON 模式更可控 |
