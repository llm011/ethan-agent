# 版式布局指南（画布 1000 × 562.5）

> 给 LLM 的排版坐标参考。所有数值单位 px，原点左上。
> 原则：**先定网格，再填元素**；元素之间留呼吸感，不要贴边、不要溢出画布。

## 全局网格

- 页边距：左右 60，上 40，下 30。内容区：`left=60, top=110, width=880, height≈400`。
- 正文页标题条：`left=60, top=36, width=880, height=56`（textType=title）。
- 标题下分隔线：line `start=[60,108] end=[940,108]`，宽 1.5，主题色或浅灰。
- 页脚：`left=60, top=530, width=880, height=20`（textType=footer，居中或右对齐）。
- 安全红线：任何元素 `left+width ≤ 940`、`top+height ≤ 540`（页脚除外）。

## cover 封面

| 元素 | 位置 | 说明 |
|---|---|---|
| 主标题 | left=100, top=190, width=800, height=80 | 居中，fontSize 40-48，bold |
| 副标题 | left=100, top=285, width=800, height=36 | 居中，textType=subtitle |
| 装饰线/色块 | 标题上方小色条 left=460, top=160, width=80, height=6 | 主题色 roundRect |
| 汇报人/日期 | left=100, top=340, width=800, height=28 | 居中，textType=notes |

变体：左文右图封面 —— 文字区 left=80,width=440；主图 left=560,top=0,width=440,height=562.5（全高出血，imageType=pageFigure）。

## contents 目录

- 标题同正文页标题条。
- 2×2 卡片网格：卡片 width=420, height=140；x = 60 / 520；y = 140 / 300。
- 每条 = itemNumber（大号编号）+ itemTitle + 一行 content 描述。
- 条目 ≤6 个；多了就分页或改成单列列表（y 步进 66）。

## transition 过渡页

- partNumber：left=80, top=180, width=200, height=120，fontSize 60+，主题色。
- 章节标题：left=80, top=310, width=700, height=60，fontSize 32-36 bold。
- 可配右侧竖条色块或浅色斑点装饰（donut/plus 形状，opacity 0.15）。

## content 正文页（按内容形态选版式）

**纯文字要点**：标题条 + 3-5 条 item 列表，item 行高 40，y 从 140 起步进 52。
用 bullet 段落或前置 itemNumber 圆点（ellipse 14×14 + 主题色）。

**左文右图**：文字 left=60, top=130, width=430；图 left=530, top=120, width=410, height=360，radius 8-16。

**三/四卡片**：卡片 width=270（三栏 x=60/365/670）或 width=205（四栏 x=60/285/510/735），
top=140, height=280；卡片 = roundRect(fill=浅主题色) + itemTitle + item 文本 + 可选 itemFigure 图标（48×48，顶部居中）。

**图表页**：图/表占 left=60, top=130, width=560, height=360；右侧结论栏 left=660, top=130, width=280（itemTitle「关键结论」+ 2-3 条 item）。图表必须有数据来源 notes（left=60, top=505）。

**大数字页**：2-3 个大数字卡片横排，数字 fontSize 44-56 bold 主题色 + 下方说明 12px。

**公式页**：公式元素居中 left=150, top=200, width=700, height=100；上下各配一行解释文字。

## end 结尾页

- 「谢谢观看 / Q&A」居中 fontSize 40 bold，top=230。
- 下方一行联系信息/副标语 textType=notes。
- 与封面同色系渐变背景收尾。

## 配色纪律

- 一页内除主题色外最多 1 个强调色；themeColors[0] 用于标题强调/图表主系列/编号。
- 浅色背景上的卡片 fill 用主题色的 8-12% 透明度色（如 #1E40AF → #EFF6FF）。
- 正文颜色直接用主题 fontColor，不要随手发明灰色。
- 深色主题（dark-tech）：卡片 fill 用 #1E293B，文字 #E2E8F0，强调 #38BDF8。

## 字数纪律（防止溢出）

- title ≤ 20 字；itemTitle ≤ 14 字；item 单行 ≤ 38 字。
- 卡片正文 ≤ 3 行 × 20 字；整页文字总量 ≤ 120 字为佳。
- 宁可分页，不要塞爆。
