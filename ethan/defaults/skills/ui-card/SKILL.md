---
name: ui-card
description: 用 A2UI v0.9.1 协议生成结构化 UI 卡片（对比/状态/统计/列表/时间轴/带按钮表单）。要调 ui_card 工具但不确定 envelope JSON 格式时，读此 skill 看协议要点、组件清单与示例。
trigger: 卡片|对比卡|状态卡|统计卡|时间轴|时间线|timeline|旅游攻略|行程|攻略|进度|排行|榜单|清单|列一下
metadata: {"openclaw": {"requires": {}}}
---

# A2UI 卡片 Skill

`ui_card` 工具的参数 `messages` 是一组 **A2UI v0.9.1 envelope**。展示结构化信息（对比 / 状态 / 进度 / 统计 / 列表 / 时间轴 / 攻略）时用 `ui_card`，比纯文字分点更直观。

## 30 秒速记

一次 `ui_card` = 一个 surface，通常 3 条 envelope 按顺序：

1. `createSurface` — 开面，给 `surfaceId` + 固定 `catalogId`
2. `updateComponents` — 组件**扁平数组**（邻接表），**必须有 `id:"root"`**，父组件用 id 引子组件
3. `updateDataModel` — 填数据（可选；静态内容直接写组件里就行）

最小例子：

```json
{"messages":[
  {"version":"v0.9.1","createSurface":{"surfaceId":"demo","catalogId":"https://a2ui.org/specification/v0_9_1/catalogs/basic/catalog.json"}},
  {"version":"v0.9.1","updateComponents":{"surfaceId":"demo","components":[
    {"id":"root","component":"Card","child":"col"},
    {"id":"col","component":"Column","children":["title","body"]},
    {"id":"title","component":"Text","text":"标题","variant":"h3"},
    {"id":"body","component":"Text","text":"正文，支持简单 markdown。"}
  ]}}
]}
```

## 4 条铁律

- **邻接表**：组件扁平数组，靠 id 拼树。容器用 `child`（单个，Card）或 `children`（数组，Row/Column/List/Timeline）。
- **必须有 `root`**：根组件 id 固定 `"root"`。
- **Button 没有 text**：必填 `child`（指向 Text 标签）+ `action`，别写 `{"component":"Button","text":"提交"}`。标题别在 text 里写 `#`/`**`（h1~h5 是纯文本，用 `variant` 控字号）。
- **catalogId** 固定 `https://a2ui.org/specification/v0_9_1/catalogs/basic/catalog.json`。

## 常用容器

- `Card`（带边框圆角，`child` 单个）、`Column`/`Row`（`children` 数组，`justify`/`align`/`weight`）、`List`（滚动列表）、`Divider`、`Icon`（material 名如 check/star/send）。
- `Timeline`（**扩展组件**，做行程/攻略/进度时间轴）：`{component:"Timeline", children:[节点1,节点2...]}`，每个节点是一个 Column/Card，自动带竖向连线 + 圆点。

## 复杂卡片先查文档

不确定组件字段或要做模板列表/数据绑定/表单时，先 `skill_read('ui-card')` 读：
- `references/catalog.md` — 全部组件必填/可选字段、enum 取值
- `references/examples.md` — 对比卡/状态卡/统计卡/模板列表/时间轴/交互卡完整 JSON
- `references/binding.md` — JSON Pointer 绑定、模板列表、`${}` 插值、表单校验
