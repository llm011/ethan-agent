# Basic Catalog 组件速查（A2UI v0.9.1）

所有组件都有 `id`（必填，唯一）和 `component`（必填，类型名）。下面只列各组件**特有**字段。
- **必填**字段标 ⭐。
- 值类型 `Dynamic*` 表示既可写字面量，也可写 `{"path":"/json/pointer"}` 数据绑定或 `{"call":"fn","args":{…}}` 函数调用。

## 文本与媒体

### Text
- ⭐`text` (DynamicString)：文本内容。
- `variant`：`h1` `h2` `h3` `h4` `h5` `caption` `body`(默认)。
- ⚠️ **只有 `body` variant 渲染 markdown**（`**粗体**`、`- 列表`、`# 标题` 等）。`h1~h5` / `caption` 是**纯文本**——标题别再写 `#`，要大字号直接用 `variant:"h3"`，别写 `text:"# 标题"`（`#` 会原样显示）。粗体同理：标题里别写 `**`。

### Icon
- ⭐`name`：图标名（Material 风格，如 `check` `info` `trending_up` `arrow_upward` `mail` `calendarToday` `send` `star` `warning`）。

### Image
- ⭐`url` (DynamicString)
- `description` (DynamicString)：alt 文本。
- `fit`：`contain` `cover` `fill` `none` `scaleDown`。
- `variant`：`icon` `avatar` `smallFeature` `mediumFeature` `largeFeature` `header`。

### Video / AudioPlayer
- ⭐`url` (DynamicString)。

## 布局容器

### Row（横向）/ Column（纵向）
- ⭐`children` (ChildList)：子组件 id 数组，或模板对象 `{"path":"/list","componentId":"tpl"}`。
- `justify`：`start` `center` `end` `spaceBetween` `spaceAround` `spaceEvenly` `stretch`。
- `align`：`start` `center` `end` `stretch`。
- `weight` (number)：在父 Row/Column 里占的弹性比例。

### Card
- ⭐`child` (ComponentId)：**单个**子组件 id（不是数组）。卡片容器，带圆角/阴影。

### List
- ⭐`children` (ChildList)：同 Row/Column，常配模板。
- `direction`：`vertical`(默认) `horizontal`。
- `align`：`start` `center` `end` `stretch`。

### Tabs
- 一组标签页，每个标签有标题 + 子组件。复杂，少用；细节查官方 spec。

### Timeline（扩展组件）
- ⭐`children` (ChildList)：节点数组，每个节点是一个 Column/Card。渲染时自动带贯穿竖向连线 + 节点圆点，适合行程/攻略/进度/步骤。
- 用法同 Column，但语义是「时间线」。例：`{"id":"tl","component":"Timeline","children":["day1","day2"]}`。

### Divider
- `axis`：`horizontal`(默认) `vertical`。分隔线。

### Modal
- 弹窗，由主内容里的按钮触发。复杂，少用。

## 交互组件

### Button
- ⭐`child` (ComponentId)：按钮标签（指向一个 Text）。**Button 自己没有 text 字段！**
- ⭐`action` (Action)：见下。
- `variant`：`default` `primary` `borderless`。

**Action 形态**：
```json
"action": {"event": {"name": "事件名", "context": {"key": "值或 {path}"}}}
```
或本地动作（如开链接）：
```json
"action": {"functionCall": {"call": "openUrl", "args": {"url": "https://..."}}}
```

### CheckBox
- ⭐`label` (DynamicString)
- ⭐`value` (DynamicBoolean)：绑定到数据模型路径，双向。

### TextField
- ⭐`label` (DynamicString)
- `value` (DynamicString)：双向绑定路径。
- `variant`：`shortText` `longText` `number` `obscured`。
- `validationRegexp` (string)。

### ChoicePicker
- 单选/多选。`options`(数组 `{label,value}`)、`value`(绑定)、`variant`(`mutuallyExclusive` 等)。

### Slider
- 数值滑块。`value`(绑定)、`min`/`max`。

### DateTimeInput
- 日期/时间输入。

## 主题（createSurface.theme，可选）
- `primaryColor`：十六进制色，如 `"#00BFFF"`，影响主按钮/高亮。
- `iconUrl` / `agentDisplayName`：归属标识。
