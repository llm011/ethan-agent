---
name: ui-card
description: 用 ui_card 工具生成结构化 UI 卡片（对比/排行/统计/时间轴/自定义）。优先用固定模板（card 参数），样式稳定；自定义场景才手写 A2UI envelope。
trigger: 卡片|对比卡|状态卡|统计卡|时间轴|时间线|timeline|旅游攻略|行程|攻略|进度|排行|榜单|清单|列一下
metadata: {"openclaw": {"requires": {}}}
---

# ui_card 卡片 Skill

展示结构化信息（对比 / 排行 / 统计 / 进度 / 时间轴 / 攻略）时用 `ui_card`，比纯文字分点更直观。

## 优先用固定模板（`card` 参数）

高频卡片**只需填结构化数据**，样式由后端模板保证——不用懂 A2UI 协议，也不会出现漏字段/不换行/样式乱的问题。`ui_card(card={...})`，`card.type` 取值：

**compare —— 对比表格**（带行列分隔线）
```json
{"type":"compare","title":"React vs Vue",
 "columns":["React","Vue"],
 "rows":[
   {"label":"核心哲学","values":["JS 做一切 (JSX)","渐进式、模板"]},
   {"label":"生态","values":["极大，跨平台强","国内繁荣，上手快"]}
 ]}
```

**rank —— 排行榜**（序号自动生成，**别自己写 1. 2. 3.**）
```json
{"type":"rank","title":"本周热门框架","subtitle":"按 GitHub stars",
 "items":[
   {"name":"React","score":"★ 223k","desc":"统治地位，生态无敌"},
   {"name":"Vue.js","score":"★ 207k","desc":"国内生态繁荣，上手快"}
 ]}
```

**stats —— 统计指标**（横向并排的大数字）
```json
{"type":"stats","title":"本月数据",
 "metrics":[
   {"label":"营收","value":"¥48,294","trend":"较上月 +12.5%"},
   {"label":"新增用户","value":"1,204"}
 ]}
```

**timeline —— 时间轴 / 行程 / 进度**（带竖线 + 圆点）
```json
{"type":"timeline","title":"丽江三日攻略",
 "nodes":[
   {"title":"Day 1 · 抵达","body":"- 古城闲逛\n- 四方街晚餐"},
   {"title":"Day 2 · 雪山","body":"- 玉龙雪山缆车\n- 蓝月谷"}
 ]}
```

**换行用真换行符 `\n`，别写 `\\n`（两个字符）**，否则不换行。

## 自定义场景才手写 A2UI（`messages` 参数）

仅当用户明确要「更花哨 / 自定义布局」、上述四种模板不够用时，才改用 `messages` 参数手写 A2UI v0.9.1 envelope。这时先 `skill_read('ui-card')` 读：
- `references/catalog.md` — 全部组件必填/可选字段、enum 取值
- `references/examples.md` — 对比卡/状态卡/统计卡/模板列表/时间轴/交互卡完整 JSON
- `references/binding.md` — JSON Pointer 绑定、模板列表、`${}` 插值、表单校验

手写 4 条铁律：
- **邻接表**：组件扁平数组，靠 id 拼树。容器用 `child`（单个，Card）或 `children`（数组，Row/Column/List/Timeline）。**每个组件都要被 root 引用到，否则报「孤儿」错。**
- **必须有 `root`**：根组件 id 固定 `"root"`。
- **Button 没有 text**：必填 `child`（指向 Text 标签）+ `action`。标题别在 text 里写 `#`/`**`（h1~h5 是纯文本，用 `variant` 控字号）。
- **catalogId** 固定 `https://a2ui.org/specification/v0_9_1/catalogs/basic/catalog.json`。
