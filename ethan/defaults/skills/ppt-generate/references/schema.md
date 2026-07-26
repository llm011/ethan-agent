# PPT-Generate 中间格式 Schema（瘦身版 PPTist）

> 本格式借鉴 [PPTist](https://github.com/pipipi-pikachu/PPTist) `src/types/slides.ts` 的骨架，
> 针对 python-pptx 渲染做了三处适配：
>
> 1. **文本 HTML → 结构化 runs**：`content: HTML` 改为 `paragraphs[{runs[{text, bold, ...}]}]`
> 2. **SVG path 形状 → 预设几何**：`path/viewBox` 改为 `shape: "roundRect"` 等 MSO 预设形状名
> 3. **latex 走 OMML 原生公式**（LaTeX→MathML→OMML，PPT 内可再编辑）；砍掉 video / audio
>
> 保留：Slide/element 整体结构、统一定位系统、`slideType`/`textType`/`imageType` 语义、
> 主题系统、chart、table、background。

## 坐标与单位

- 画布默认 **1000 × 562.5 px**（16:9），与 PPTist 视口一致；原点左上角。
- 所有 `left/top/width/height`、字号、线宽、阴影偏移均为 **px**（相对画布）。
- 渲染换算：`EMU = px × 12192000 / canvas.width`（1000px 画布时 1px = 12192 EMU）；
  字号 `pt = px × 0.96`。
- `rotate` 单位为度，顺时针。

## 顶层结构

```json
{
  "version": 1,
  "canvas": { "width": 1000, "height": 562.5 },
  "theme": "business-blue",
  "slides": [ /* Slide[] */ ]
}
```

- `theme`：主题名（`scripts/themes/<name>.json`）或内联 SlideTheme 对象。
- `canvas` 可省略，默认 1000×562.5。自定义比例（如 4:3 用 1000×750）时渲染器按宽度换算。

### 项目目录模式（逐页生成，推荐）

slides 也可以不放 deck.json 里，而是拆成项目目录——`render_pptx.py` / `gen_image.py` 的 deck 参数传目录即可：

```
<项目目录>/
  deck.json      # 顶层结构去掉 slides：version / canvas / theme（通常内联定制主题）
  pages/*.json   # 每页一个 Slide 对象，按文件名排序合并为 slides（NN_ 前缀控序，如 01_cover.json）
  assets/        # gen_image.py 解析出的图片（项目模式下默认输出到这里）
```

页文件内容就是单个 Slide JSON（`{"id","type","background"?,"remark"?,"elements":[...]}`），字段定义与下文 Slide 完全一致。校验报错里的 `slides[i]` 对应排序后第 i 个页文件。

## Slide

```json
{
  "id": "s1",
  "type": "cover",
  "background": {
    "type": "solid",
    "color": "#FFFFFF"
  },
  "remark": "演讲者备注，写入 pptx notes",
  "elements": [ /* PPTElement[]，数组顺序即 z-order，先底后顶 */ ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 必填，唯一 |
| `type` | SlideType | `cover` 封面 / `contents` 目录 / `transition` 过渡页 / `content` 正文 / `end` 结尾。影响 LLM 的版式选择，渲染器不强制 |
| `background` | object | 见下；省略时用主题 `backgroundColor` |
| `remark` | string | 演讲者备注 |
| `elements` | array | 元素列表 |

### SlideBackground

```json
{ "type": "solid", "color": "#0F172A" }
{ "type": "gradient", "gradient": { "type": "linear", "rotate": 135, "colors": [{ "pos": 0, "color": "#1E40AF" }, { "pos": 100, "color": "#3B82F6" }] } }
{ "type": "image", "image": { "src": "assets/bg.jpg", "size": "cover" } }
```

- gradient `pos` 为 0–100 百分比；`rotate` 仅线性渐变有效。
- image `size` 支持 `cover`（默认，裁切填满）/ `contain`（等比缩放居中，不足处露底色）。

## 元素通用属性（PPTBaseElement）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✅ | 唯一 |
| `type` | string | ✅ | `text`/`image`/`shape`/`line`/`chart`/`table` |
| `left/top/width/height` | number | ✅ | px。`line` 元素除外（用 start/end） |
| `rotate` | number | | 旋转角度，默认 0 |
| `name` | string | | 元素名（写入 pptx shape name，便于二次编辑时辨认） |

## 1. 文本元素（text）

```json
{
  "id": "t1",
  "type": "text",
  "left": 60, "top": 40, "width": 880, "height": 60,
  "textType": "title",
  "paragraphs": [
    {
      "align": "left",
      "lineHeight": 1.3,
      "spaceBefore": 0,
      "spaceAfter": 5,
      "bullet": false,
      "runs": [
        { "text": "年度报告", "bold": true, "fontSize": 30, "color": "#111827" },
        { "text": " 2026", "fontSize": 30, "color": "#1E40AF" }
      ]
    }
  ],
  "vAlign": "top",
  "inset": [0, 0, 0, 0],
  "fill": null,
  "outline": null,
  "opacity": 1,
  "vertical": false
}
```

### textType 语义（主题 typography 据此给默认字号/颜色/字重）

| textType | 用途 | 典型场景 |
|---|---|---|
| `title` | 页面主标题 | 每页顶部 |
| `subtitle` | 副标题 | 封面/过渡页 |
| `content` | 正文段落 | 内容区 |
| `item` | 列表项正文 | 要点列表 |
| `itemTitle` | 列表项标题 | 卡片/条目的小标题 |
| `notes` | 注释小字 | 数据来源、脚注 |
| `header` | 页眉 | 顶部固定信息 |
| `footer` | 页脚 | 页码、公司名 |
| `partNumber` | 部分编号 | 过渡页大号数字 "01" |
| `itemNumber` | 条目编号 | 列表前序号 |

### paragraph 字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `align` | `left/center/right/justify` | left | 水平对齐 |
| `lineHeight` | number | 1.5 | 行高倍数 |
| `spaceBefore/spaceAfter` | number | 0/5 | 段前/段后间距 px |
| `bullet` | false / `"bullet"` / `"number"` | false | 项目符号 / 自动编号 |
| `runs` | array | ✅ | run 列表 |

### run 字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `text` | string | ✅ | 文本内容 |
| `bold` `italic` `underline` `strikethrough` | bool | false | 字重样式 |
| `sub` `sup` | bool | false | 下标/上标（行内数学符号用，如 `d` + `{"text":"k","sub":true}`） |
| `fontSize` | number | 主题 typography | px |
| `color` | string | 主题 typography | `#RRGGBB` |
| `fontName` | string | 主题 fontName | 字体名 |

> run 级缺省字段沿 textType 的主题默认值；一个段落内可用多个 run 实现混色/混排。
> **不要**在 text 里塞 HTML 标签，渲染器不做解析。

其他：`vAlign`（`top/middle/bottom`，默认 top）；`inset`（内边距 `[上,右,下,左]` px，默认 `[10,10,10,10]`）；`fill`/`outline` 给文本框加底色/边框；`vertical: true` 竖排文本。

## 2. 图片元素（image）

```json
{
  "id": "img1",
  "type": "image",
  "left": 560, "top": 120, "width": 380, "height": 320,
  "src": "assets/office.jpg",
  "imageType": "pageFigure",
  "radius": 12,
  "fit": "cover",
  "flipH": false, "flipV": false,
  "outline": { "style": "solid", "width": 1, "color": "#E5E7EB" },
  "opacity": 1
}
```

- **`imageType` 语义**（对接图片瀑布流）：
  - `pageFigure`：页面主图/配图（大图，视觉焦点）
  - `itemFigure`：条目配图/图标（小图）
  - `background`：背景图（通常配合 background.image 使用）
- **`src` 三种形态**：
  - 本地路径（相对 deck JSON 所在目录）或绝对路径
  - `https?://...`：渲染器自动下载到临时目录
  - `gen:搜索词`（如 `gen:modern office building`）：占位符，**必须先跑 `gen_image.py` 解析成真实文件**；渲染器遇到未解析的 `gen:` 会报错退出
  - `icon:collection:name`（如 `icon:mdi:rocket-launch`）：Iconify 图标占位符，同样由 `gen_image.py` 解析
- `fit`：`cover`（默认，裁切填满）/ `contain` / `fill`（拉伸）。
- `radius`：圆角 px（通过 roundRect 裁剪实现）。
- 额外占位字段 `imageQuery`：src 缺省时给 gen_image.py 的搜索词（等价于 `gen:`）。

## 3. 形状元素（shape）

```json
{
  "id": "sh1",
  "type": "shape",
  "left": 60, "top": 120, "width": 270, "height": 140,
  "shape": "roundRect",
  "fill": "#EFF6FF",
  "gradient": null,
  "outline": { "style": "solid", "width": 1, "color": "#BFDBFE" },
  "opacity": 1,
  "shadow": { "h": 0, "v": 4, "blur": 12, "color": "#0000001A" },
  "text": {
    "align": "middle",
    "paragraphs": [ { "align": "center", "runs": [ { "text": "核心指标", "bold": true, "fontSize": 18, "color": "#1E40AF" } ] } ]
  }
}
```

- `shape`：python-pptx 预设几何名（下表），**不支持任意 SVG path**。
- `fill` / `gradient` 二选一（gradient 优先）；都可省略（无填充）。
- `text`：形状内文本，结构同 text 元素的 paragraphs + `align`（垂直对齐）。

### 支持的预设形状名

| 分类 | shape 名 |
|---|---|
| 矩形 | `rect` `roundRect` `round1Rect` `round2SameRect` `round2DiagRect` `snip1Rect` `snip2SameRect` `snip2DiagRect` `snipRoundRect` |
| 基础 | `ellipse` `triangle` `rtTriangle` `diamond` `parallelogram` `trapezoid` `pentagon` `hexagon` `heptagon` `octagon` `plus` `donut` |
| 箭头 | `rightArrow` `leftArrow` `upArrow` `downArrow` `leftRightArrow` `upDownArrow` `bentArrow` `chevron` `notchedRightArrow` |
| 星/旗 | `star4` `star5` `star6` `star8` `ribbon` `ribbon2` `wave` `doubleWave` |
| 对话/标注 | `roundRectBubble` `ellipseBubble` `cloudBubble` `wedgeRectCallout` `wedgeRoundRectCallout` `wedgeEllipseCallout` |
| 其他 | `heart` `cloud` `sun` `moon` `cube` `can` `teardrop` `frame` `halfFrame` `corner` `diagStripe` `foldedCorner` `smileyFace` `lightningBolt` `bracketPair` `bracePair` `blockArc` `pie` `chord` |

（映射到 python-pptx `MSO_SHAPE`；渲染器遇到未知名会报可用列表。）

## 4. 线条元素（line）

```json
{
  "id": "l1",
  "type": "line",
  "start": [60, 110],
  "end": [940, 110],
  "width": 2,
  "style": "solid",
  "color": "#E5E7EB",
  "points": ["", "arrow"]
}
```

- `start`/`end`：起终点坐标 `[x, y]`（无 width/height 概念）。
- `style`：`solid/dashed/dotted`；`points`：端点样式 `[起点, 终点]`，可选 `""`/`arrow`/`dot`。
- 仅支持直线（connector）。折线/曲线请用多个 line 拼接。

## 5. 图表元素（chart）—— 原生 pptx 图表，可编辑数据

```json
{
  "id": "c1",
  "type": "chart",
  "left": 60, "top": 130, "width": 540, "height": 340,
  "chartType": "column",
  "data": {
    "labels": ["Q1", "Q2", "Q3", "Q4"],
    "legends": ["营收", "利润"],
    "series": [[120, 150, 180, 210], [30, 45, 52, 68]]
  },
  "options": { "stack": false, "lineSmooth": true },
  "themeColors": ["#1E40AF", "#F59E0B"]
}
```

- `chartType`：`column`（柱状）/ `bar`（条形）/ `line` / `pie` / `ring`（环形）/ `area` / `radar` / `scatter`。
- `data.series[i]` 对应 `legends[i]`，长度与 `labels` 一致。pie/ring 只用 series[0]。
- `options.stack`：堆叠（column/bar/area/line 有效）。
- `themeColors` 省略时用主题 themeColors 循环取色。

## 6. 表格元素（table）

```json
{
  "id": "tb1",
  "type": "table",
  "left": 60, "top": 140, "width": 880, "height": 300,
  "colWidths": [0.34, 0.33, 0.33],
  "cellMinHeight": 40,
  "outline": { "style": "solid", "width": 1, "color": "#E5E7EB" },
  "theme": { "color": "#1E40AF", "rowHeader": true, "rowFooter": false, "colHeader": false, "colFooter": false },
  "data": [
    [ { "text": "指标", "colspan": 1, "rowspan": 1, "style": { "bold": true, "color": "#FFFFFF", "align": "center" } },
      { "text": "2025", "style": { "bold": true, "color": "#FFFFFF", "align": "center" } },
      { "text": "2026", "style": { "bold": true, "color": "#FFFFFF", "align": "center" } } ],
    [ { "text": "营收（亿）" }, { "text": "120" }, { "text": "158" } ]
  ]
}
```

- `colWidths`：各列宽度占比，和为 1。
- 单元格：`text` + `colspan`/`rowspan`（合并）+ `style`（`bold/em/underline/strikethrough/color/backcolor/fontSize/fontName/align/vAlign`）。
- `theme.rowHeader` 为 true 时首行用 `theme.color` 填充、加粗，文字颜色按表头底色亮度自动选黑/白（单元格 style 可再覆盖）。
- 表体默认填充跟随主题背景：深色主题下自动提亮一档作卡片面（文字用主题 fontColor），浅色主题下为纯白；边框默认取主题 outline 颜色。深浅主题下表格都可读，无需手写 backcolor。
- 被合并覆盖的单元格写 `{ "text": "", "merged": true }` 占位。

## 7. 公式元素（latex）—— 原生文本 run + 真上下标，全平台可编辑

```json
{
  "id": "f1",
  "type": "latex",
  "left": 200, "top": 200, "width": 600, "height": 120,
  "latex": "E = mc^2 + \\frac{a}{b} + \\sqrt{x} + \\sum_{i=1}^{n} i",
  "fontSize": 24,
  "color": "#1F2937",
  "align": "center"
}
```

- `latex`：LaTeX 公式源码（不需要 `$...$` 包裹）。支持 `\frac \sqrt ^ _ \sum \prod \int \partial`、
  希腊字母、`\mathrm \text`、常用符号（`\cdot \otimes \infty \leq` 等）。
- **默认引擎 omml**：LaTeX→MathML→OMML，照 Mac Office 365 原生公式的字节模式注入
  （裸 `a14:m`、Cambria Math 字体声明、结构元素带 `m:ctrlPr`、`m:rad` 带空 `m:deg`+`degHide`）
  ——真根号（带横线）、真分式（上下堆叠），在 PowerPoint（Win/Mac）和 WPS 里都可再编辑。
  **Keynote 不支持 `a14:m`**（会判整个文件非法），需要 Keynote 交付时改用 runs 引擎。
- `engine: "runs"`（可选）：LaTeX → PPT 原生文本 run（`\frac{a}{b}` → 行内式 `(a)/(b)`，
  上下标用真实 baseline run）——全平台（含 Keynote）可见可编辑，代价是根号没有横线、
  分式不堆叠。仅在明确要交付 Keynote 用户时逐元素指定。
- `fontSize`（默认 20px）、`color`（默认主题 fontColor）、`align`（默认 center）。
  LaTeX 源码会写入形状描述（选择窗格可见），方便对照手动微调。
- 转换失败时降级为公式源码纯文本并输出警告，不阻断整页渲染。
- omml 引擎依赖 `latex2mathml` + `mathml2omml`（渲染器自动 pip install）；runs 引擎零依赖。

## SlideTheme（主题对象）

```json
{
  "name": "business-blue",
  "backgroundColor": "#FFFFFF",
  "themeColors": ["#1E40AF", "#3B82F6", "#93C5FD", "#F59E0B", "#10B981"],
  "fontColor": "#1F2937",
  "fontName": "Microsoft YaHei",
  "latinFontName": "Verdana",
  "outline": { "style": "solid", "width": 1, "color": "#D1D5DB" },
  "shadow": { "h": 0, "v": 2, "blur": 8, "color": "#00000014" },
  "typography": {
    "title":      { "fontSize": 28, "color": "#111827", "bold": true },
    "subtitle":   { "fontSize": 16, "color": "#4B5563" },
    "content":    { "fontSize": 14, "color": "#1F2937" },
    "item":       { "fontSize": 14, "color": "#1F2937" },
    "itemTitle":  { "fontSize": 16, "color": "#111827", "bold": true },
    "notes":      { "fontSize": 10, "color": "#9CA3AF" },
    "header":     { "fontSize": 10, "color": "#6B7280" },
    "footer":     { "fontSize": 10, "color": "#6B7280" },
    "partNumber": { "fontSize": 60, "color": "#1E40AF", "bold": true },
    "itemNumber": { "fontSize": 16, "color": "#1E40AF", "bold": true }
  }
}
```

- `themeColors[0]` 为主色，图表/装饰默认取它。
- `fontName` 是中文（ea/cs）字体；`latinFontName` 是西文（latin）字体，缺省与 `fontName` 相同。两者分离可实现「中文微软雅黑 + 英文 Verdana」式混排。run 级显式 `fontName` 会同时覆盖中西文。
- `typography` 是本格式对 PPTist SlideTheme 的扩展：按 textType 给 run 级默认值。
- 预设主题见 `scripts/themes/`；deck 顶层 `theme` 字段写主题名即可。

## PPTist 字段别名（兼容层）

渲染器同时接受以下 PPTist 原生命名，PPTist 导出的 JSON 可近直接喂入：

| PPTist 原生字段 | 本格式字段 | 位置 |
|---|---|---|
| `fontsize` / `fontname` | `fontSize` / `fontName` | run、表格单元格 style |
| `paragraphSpace` | `spaceAfter` | paragraph |
| `defaultFontName` / `defaultColor` | （元素级 run 缺省） | text 元素、shape.text |

## 已明确不支持（设计决策，勿生成）

| PPTist 特性 | 原因 | 替代 |
|---|---|---|
| `content: HTML` | python-pptx 需要 run 级结构 | paragraphs/runs |
| shape 任意 SVG `path` | pptx 只支持预设几何 | 预设 shape 名 |
| `video` / `audio` | 无法原生可编辑渲染 | 以 image 截图代替（外部生成） |
| 元素动画 `animations` / 翻页 `turningMode` | python-pptx 不支持时间轴 | 不做 |
| line 折线/曲线控制点 | connector 仅直线 | 多段 line 拼接 |
| image 滤镜 `filters` / `colorMask` | CSS 概念，pptx 无对应 | 预处理图片后插入 |
