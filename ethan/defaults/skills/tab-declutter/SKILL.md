---
name: tab-declutter
description: 轻量整理本机 Chrome 的浏览器 tab：去重复、清无用（blank/new tab）、清时效性短的页面（如 code.byted.org
  的 code review 页），再把剩余 tab 按主题分组，无法明确归类的保持不分组。
trigger:
- 整理tab
- 整理 tab
- 整理标签页
- 整理 标签页
- 整理浏览器
- 整理 浏览器
- tab整理
- tab 整理
- 清理tab
- 清理 tab
- tab分组
- tab 分组
- 标签页整理
- 标签页 整理
- 整理一下标签页
- 整理一下 tab
- 标签页太多
- tab 太多
- declutter tab
- declutter tabs
---

# tab-declutter

轻量整理本机 Chrome 的 tab：**去重 → 清无用 → 分组**，全程用 `browser_tab` 操作本机真实 Chrome。判断全在内存里做完，整个流程通常 **2 次工具调用**：`user_list` 拉清单 + `organize` 一次性执行（多端连接时前置一次 `browser_client`）。

## 硬规则（先读这五条）

1. **直接执行到底，不中途询问。** 不问「要不要关」「按这个清单吗」，不等用户点头。关闭清单放在**执行后**的汇报里呈现。真正无法判断价值的才留着——别拿「拿不准」当借口把该关的也留着。
2. **每组至少 2 个 tab。** 单 tab 组没有聚合价值，反而把时间线切碎。新建时不建；**已有的单 tab 组用 `ungroup_all` 解散**，让那个 tab 回游离（用户明确要求过，别留着「看起来有个组」）。
3. **组名必带 `🦊 ` 前缀 + 真实业务名**（如 `🦊 HTML 优化`）。禁止「文档资料」「其他文档」「杂项」这类兜底名——出现即代表没拆够，回炉重拆。**每个 group op 的 title 都要带**，不要只在汇报里写。
4. **归不了类就保持游离**，不硬塞进组。分组只是归到 Chrome Tab Group，不改 tab 内容，可放心做。
5. **汇报前重新 `user_list` 核验**，以真实数据为准：还剩几个 tab、几个在组里、有没有单 tab 组。组名以 `organize` 返回的 `applied.grouped[].title` 为准（`user_list` 不返回组名，别凭记忆编）。

## 前置：确认浏览器客户端

多端连接时必须先选目标：

```
browser_client(action="list")   # 多个客户端 → browser_client(action="use", name=...)
```

只有一个客户端时自动选中，跳过。

## 第 1 步：拉清单

```
browser_tab(action="user_list")
```

拿到全部 tab 的 `tabId` / `windowId` / `groupId` / `url` / `title` / `active`。字段是驼峰 `tabId`（不是 `tab_id`）；`groupId` 为 `-1` 表示游离。**后续所有判断基于这份清单，不臆造 tab。**

## 第 2 步：分类打标（内存里做，不输出）

对每个 tab 打 A/B/C/D 标。**中间清单不吐给用户**，最终清单随汇报呈现。

| 类 | 判定 | 动作 |
|---|---|---|
| **A 重复** | URL 归一化后相同（去末尾 `/`、`#...` 锚点、无意义 `utm_*` 等 query）；同 URL 不同端口、本地 + 线上部署也算重复 | 留 1 个（优先 active，否则第一个），其余 close |
| **B 无用页** | `about:blank`；`chrome://newtab`、`chrome://new-tab-page`；title 为「新标签页 / New Tab」且 url 为空的；空白/错误占位页 | close |
| **C 低价值页** | `code.byted.org` 的 code review / diff / MR 详情（看完即过期）；门户/首页/入口页（百度首页、飞书云空间首页、搜索引擎首页、空壳工作台）；单次排查报告；已过期的临时方案/工位调整等时效文档 | close |
| **D 保留** | 其余有价值的 tab | 按下面两层归类分组 |

- **A 的例外**：同表不同视图 / 不同 `table_id` 是两张不同的表，**不算重复**，都保留。
- **C 的边界**：其余域名同样按此精神判断，明显没用过/无实质内容的一律直接关，不必再问。

### 两层归类（D 类的重点）

> ⚠️ **踩坑（已被用户纠正）**：飞书文档**全是** `larkoffice.com`，止步于「按平台归类」会把一大批文档粗暴塞进一个「文档资料」大组——用户根本分不清哪个是哪个，等于没分。业务 tab 里飞书文档占绝大多数，**按平台只是起点，必须下沉到业务主题/项目名**，不是按站点归类。

**第一层——按内容类型 / 平台粗分**：

- 飞书文档（`*.larkoffice.com` / `*.feishu.cn` 的 `docx`/`wiki`）、多维表格（链接带 `base` 或 `/base/`、`table=`）、飞书表单（`share/base/form`）
- 字节内部平台（`*.bytedance.net`、`cloud.bytedance.net`、`slardar`、`code.byted.org`、`mcp.bytedance.net` 等）
- GitHub（`github.com`）、技术文章/阅读（`bytetech.info`、各类 blog/文档站、`*.github.io`）、本地/开发（`localhost`、`127.0.0.1`）
- 其它按主域名或产品名粗分

**第二层——按标题关键词拆成业务组**（必须做）：

1. **项目/主题前缀**优先：标题里反复出现的专有名词（「CCM」「HTML」「扣子3.5」「豆包」）→ 直接用它命名
2. **文档性质 + 业务**次之（「评测/审计」「PRD/方案」「排期」「团队梳理」）——性质太泛时仍要叠业务词，「评测·审计」优于单叫「报告」
3. **同业务的上下游文档**（PRD、技术方案、问题列表、设计稿）**归到同一组**——按业务线拆，不按文档类型拆

**容量与命名**：每组 **2~7 个**，超过 8 个说明没拆够，继续按上面依据细分。组名 2~6 字（如「HTML 优化」「CCM 团队」「评测·审计」「豆包·PRD」）。配色 grey/blue/red/yellow/green/pink/purple/cyan/orange，相近大类用相近色系。

**落单**：找不到 ≥2 个同类就保持游离。落单前先多想一轮——同业务/同产品的两个 tab（如都是 Ethan 相关）足以成组，别图省事直接当游离。

## 第 3 步：一次 `organize` 执行完

**所有操作打包成一个调用**，不逐步执行：

```python
browser_tab(action="organize", ops=[
  # 1) 先关：A/B/C 类全部 tab id
  {"op": "close", "tabs": [id1, id2, ...]},
  # 2) 再解散不合格的旧组（单 tab 组、主题已散的组）—— 用 groupId，别用 title
  {"op": "ungroup_all", "groupId": gid1},
  # 3) 再建组：每个主题一条，title 必带 🦊 前缀 + 真实业务名（不是类型名）
  {"op": "group", "title": "🦊 HTML 优化", "tabs": [id3, id4, ...], "color": "blue"},
  {"op": "group", "title": "🦊 CCM 团队", "tabs": [id5, id6, ...], "color": "purple"},
  {"op": "group", "title": "🦊 扣子·调研", "tabs": [id7, id8, ...], "color": "green"},
])
```

- **op 顺序**：`close` → `ungroup_all` → `group`。先关掉要删的，再拆不合格的组，最后分剩余的。落单 tab 不加 `group` op。
- tab 已消失 / 已不在任何组 → 自动 skip，不报错（`skipped` 非空是正常的，不是错误）。
- 所有操作在扩展侧批量执行，不在浏览器前台弹页面。

**解散/摘组**：解散整组用 `{"op": "ungroup_all", "groupId": N}`。**groupId 从 `user_list` 的 `groupId` 字段读，优先用它**——`title` 查找很脆：同名组跨窗口会直接报错并打断整批 ops（前面的 `close` 已落地、后面的 `group` 全没跑），查不到则静默跳过。只把某几个 tab 摘出组、组里还剩 ≥2 个时用 `{"op": "ungroup", "tabs": [id, ...]}`。

**组内排序**：`tabs` 数组顺序即组内顺序——同项目/同标题前缀的挨在一起 → 同文档性质（PRD 挨 PRD、报告挨报告）→ 标题字典序兜底。

### 折叠（默认自动）

整理后自动折叠本次涉及的 TabGroup，**跳过含当前活跃 tab 的那组**（不打断你正在看的）。返回里 `applied.collapsed` 是已折的 groupId，`applied.collapseSkipped` 是被跳过的。只有用户**明确要求**「连当前这组也折」才传 `collapse=true`，「都不要折」才传 `collapse=false`。折叠失败不影响整理结果（组可能已被 Chrome 销毁），不要为此重试或报错。

汇报时带一句「已自动折叠 N 组，当前使用中的那组保持展开」。

## 第 4 步：汇报

先重新 `user_list` 核验（硬规则 5），再给一段简洁汇报：

- 关闭了几个（重复 X / 无用 Y / 时效 Z，列出 title）
- 分了几组（组名取自 `applied.grouped[].title` + 每组 tab 数，每组均 ≥2）
- 哪些落单未分组（说明「单条不成组」）

干净直接，不输出中间调试日志。

## 关闭日志（记录到 Obsidian）

执行完把「关掉的实质页面」用 `knowledge_edit` 追加到 `work/tab-declutter-log.md`（默认 `append`，加到**文末**，每批一条、新的一批在下面）。**只记有回看价值的**（重复副本、时效性 code review、被关的文档）；blank/newtab 这类纯垃圾不记。每条写成 markdown 链接 `[title](url)`，方便点回去：

```
## 2026-09-22 10:30

**关闭 7 个：**
- [重复] [CCM HTML OnePage(WIP)](https://bytedance.larkoffice.com/wiki/LAav...) ×2（留 1）
- [时效] [stone/coze-claw](https://code.byted.org/stone/coze-claw)
- [无用] [没有权限访问 - 飞书云文档](https://bytedance.larkoffice.com/wiki/VMGG...)
```

## 边界与安全

- 关闭 tab 不可逆——但 A/B/C 类按用户明确要求**直接关、不逐项征询**；只有既非重复、也非明显无用的才留。
- 不碰 tab 内容：不填表、不点击页面内元素。
- 只整理当前这一个浏览器客户端的 tab。
- **连接被顶替报错**时：先 `browser_client(action="use", name=...)` 重连 → 重新 `user_list` 拿最新 tabId → 重跑 `organize`。重跑安全（已关的会以 `skipped: not found` 返回，不误关、不重复）。若上次已部分生效（关闭落地、仅分组未应用），以最新 `user_list` 为准补齐差异。
