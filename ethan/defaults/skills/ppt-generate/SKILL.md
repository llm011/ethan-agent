---
name: ppt-generate
description: "从一句话/大纲/文档生成原生可编辑的 PPT（.pptx）。项目制逐页生成：先定大纲与专属 design system，再每页独立构思版式/内容/衔接，渲染为 python-pptx 原生矢量元素——文本、形状、图表、表格、公式全部可在 PowerPoint/WPS 里二次编辑。当用户说「做PPT」「生成幻灯片」「写个汇报PPT」「把这份文档做成演示文稿」「pptx」「slides」「presentation」「课件」时触发。"
trigger: "PPT|ppt|pptx|幻灯片|演示文稿|slides|presentation|deck|做PPT|生成PPT|汇报PPT|课件|keynote"
version: 2.0.0
display_name: PPT 生成器
platforms: [macos, linux, windows]
metadata:
  openclaw:
    requires:
      bins:
        - python3
---

# PPT 生成器（项目制逐页生成 · PPTist schema · python-pptx 渲染）

把自然语言需求变成**原生可编辑**的 pptx：不是图片拼贴，每个文本框、形状、图表、表格、公式都是 PPT 原生元素，用户打开就能改。

好 deck 不是一次写出来的，是**逐页设计**出来的：先定全局（大纲 + 专属 design system），再每页单独构思版式、内容、和前后页的衔接，最后逐页复审返修。本技能的工作流就按这个节奏组织。

## 工作流（严格按顺序）

```
需求 → ①大纲(含衔接设计) → ②design system → ③建项目目录 → ④逐页生成
     → ⑤gen_image.py 填图 → ⑥--check 校验 → ⑦渲染 → ⑧逐页复审/单页返修 → 交付
```

### Step 1：规划大纲（含衔接设计）

- 先输出大纲给用户（除非用户说直接生成）：每页定 `slideType`（cover/contents/transition/content/end）和核心内容。
- **叙事按金字塔原理**：全 deck 一个核心结论（写进封面副标题），每章一个分结论，每页一个 action title（**完整观点句，带数字或机制名**，不是名词短语）。动机页用 SCQA（情境-冲突-问题-答案）。
- **整体↔细节结构**：机制/架构类主题必须有「总览页」——全景图 + 编号圆圈 ①②③④；后续细节页带同编号锚点，细节讲完放「回扣页」闭环（总-分-总）。
- **衔接设计（逐页生成质量的源头）**：大纲里每页除了 action title、2-4 个支撑要点（含具体数字/机制）、页面角色（总览/细节①/对比/结论）、锚点编号，还要写一条**衔接备注**：
  - 承上：本页回收/回答上页留下的什么钩子；
  - 启下：本页给后面哪页埋什么钩子（如「先记住这个公式，第 9 页我们亲手算一遍」）。
  前后页的显式引用（页码、章节名）会让 deck 读起来是一个整体而不是一摞单页。
- **只给主题、没给素材时**：大纲内容来自模型自身知识；若主题涉及最新资讯/实时数据/具体数字（如「2026 年行业趋势」「某公司最新财报」），先用 web_search 检索再写大纲，并在交付时说明哪些内容来自检索。
- 页数：默认 6-10 页；用户没说要目录/过渡页就不加。

### Step 2：定制本 deck 的 design system

不要直接从预设主题里挑一个了事——每个值得认真做的 deck 都该有一套**为它定制的视觉语言**：

1. **读 `references/fonts.md`**：按 deck 气质（学术/商务/科技/营销）和交付平台选定中西文字体配对（中文 ea 字体 + 西文 latin 字体分离设置）。
2. **给这套设计语言起个名字、定一组规则**，在大纲确认时一并告知用户，例如「地图策略：纸白底 + 深海军蓝主色 + 灰调皇家蓝强调 + 朱红警示 + 路线/坐标装饰语法」。规则至少包括：
   - 主色 / 强调色（≤1 个）/ 语义色（如「Encoder 蓝、Decoder 粉」全 deck 一致）——**主色往灰调一档更雅致**（如灰调皇家蓝 `#4A5FA8`，不用高饱和纯钴蓝）；
   - 装饰语法：编号圆圈、章节导航点、分隔线、卡片形态（圆角？描边？投影？）——全 deck 统一；
   - 字体配对与字号阶梯（标题/正文/注释）。
3. **落成内联 theme 对象**写进项目 `deck.json`（结构见 schema.md 的 SlideTheme，`typography` 按 textType 给默认值）。预设主题（business-blue / dark-tech / fresh-green / vibrant-orange）只作为快速兜底或定制起点，可在其基础上改色改字体。

### Step 3：建项目目录

```
<输出目录>/<项目名>/
  deck.json        # version / canvas / theme（Step 2 的内联主题），不含 slides
  pages/           # 每页一个 JSON，Step 4 逐页写入
```

- 项目名用人类可读命名（如 `Transformer详解课件/`）。
- `deck.json` 骨架：`{"version": 1, "canvas": {"width": 1000, "height": 562.5}, "theme": {...内联主题...}}`。
- ≤5 页的小 deck 可以走旧的单文件模式（一个含 slides 的 deck.json），但逐页生成 + 复审的效果更好，默认用项目制。

### Step 4：逐页生成（本工作流的核心）

**一次只写一页**：`pages/NN_slug.json`（NN 两位序号保证排序，如 `01_cover.json`、`05_attention_intro.json`），文件内容是单个 Slide 对象（`{"id","type","background"?,"remark"?,"elements":[...]}`）。

每写一页之前，显式过三遍再落笔（可以在回复里用一两句话说明设计意图）：

1. **版式**：本页从 layout-guide 版式库选哪个骨架？为什么适合这段内容？（三卡片 / 左右论点-证据 / 图表页 / 公式页 / 流程图页…）
2. **内容**：action title 是不是观点句？2-4 个区块形态是否错开？每条 bullet 有没有数字/机制/对比？密度够不够（构件清单见 layout-guide）？
3. **衔接**：kicker 与章节导航点对不对？总览锚点编号是否全局一致？本页是否兑现了大纲里的承上/启下钩子（该引用的页码要写进文案）？

- **Schema 全文见 `references/schema.md`**（元素字段、形状名表、主题结构），写之前必读。
- **排版必读 `references/layout-guide.md`**：咨询式页面骨架、版式库、信息密度标准、衔接与设计语言规则。
- 画布固定 1000×562.5；文本用结构化 runs，**不写 HTML**；形状只用预设名，**不写 SVG path**。
- 公式页用 `latex` 元素（OMML 原生公式，PPT 里可再编辑），不要画成图片。
- 图片先用占位符：
  - 照片/配图 → `"src": "gen:modern office skyline"`（英文搜索词效果更好）
  - 图标 → `"src": "icon:mdi:rocket-launch"`（Iconify 集合:名称，如 mdi/fa/carbon）
  - 用户提供的图 → 直接写本地路径
- 演讲者备注写进该页 JSON 的 `remark` 字段。

### Markdown 输入约定（用户给 md 大纲时）

用户可能直接给一份详细的每页规划 md。按以下映射转成逐页 JSON：

```markdown
# PPT 主题：大模型时代的搜索架构
主题：dark-tech          ← 可选，映射 theme（此时可不做 Step 2 定制）
页数：8                  ← 可选

## 第1页 [封面]
标题：大模型时代的搜索架构
副标题：从倒排索引到向量召回

## 第2页 [目录]
- 检索范式的三次迁移：关键词→语义→生成式
- 向量召回的工程落地：HNSW 与 IVFFlat

## 第3页 [正文] 检索范式对比
版式：三卡片            ← 可选，映射 layout-guide 版式
- 卡片1 icon:mdi:magnify 关键词检索：倒排+BM25，精确强、语义弱
- 卡片2 icon:mdi:vector-point 向量检索：Embedding+ANN，语义强
- 卡片3 icon:mdi:brain 生成式：RAG，成本高

## 第4页 [正文] IVFFlat 原理
公式：\mathrm{Recall@K} = \frac{|S_K \cap S_K^*|}{K}   ← 映射 latex 元素
要点：
- nlist 取 √N 量级
- nprobe 是召回/延迟旋钮
表格：                      ← 映射 table 元素
| nprobe | Recall@10 | P99 |
| 8 | 0.86 | 6ms |
| 64 | 0.97 | 21ms |

## 第5页 [正文] 上线效果
图表：柱状图               ← 映射 chart 元素，数据必须给出
| 月份 | nDCG@10 | 召回率 |
| 1月 | 0.61 | 0.72 |
配图：gen:server room data center   ← 映射 gen: 占位符
备注：强调延迟只涨 8ms        ← 映射 slide.remark

## 第6页 [结尾]
谢谢观看
```

映射规则：`[封面/目录/过渡/正文/结尾]`→slideType；`公式：`→latex；`表格：`后的 md 表格→table；`图表：`+数据表→chart；`gen:`/`icon:`→图片占位；`备注：`→remark。用户没写页类型时按内容推断（第 1 页默认封面、最后默认结尾）。md 里没给的细节（精确坐标、字号）按 layout-guide 补齐。

**忠实原则**：md 里写明的页数、页序、文案、公式、表格/图表数据必须原样进入页面 JSON，不增页、不减页、不改写观点、不编造 md 里没有的数据。可自由发挥的只有视觉层：版式选择、坐标、字号微调、装饰元素、配图选词。md 内容明显有误或遗漏时先问用户，不要擅自扩写。

### Step 5：填充图片

```bash
python3 ~/.ethan/skills/ppt-generate/scripts/gen_image.py /path/to/<项目目录>
```

- 传项目目录即可：自动合并 `pages/*.json`，解析后**逐页原地回写**，图片存到项目内 `assets/`。
- 瀑布流：Pexels（需 `PEXELS_API_KEY`）→ Unsplash（需 `UNSPLASH_ACCESS_KEY`）→ AI 生图（需 `ETHAN_IMAGE_GEN_API_KEY`）→ 纯色占位图（保底，永不失败）。
- Iconify 图标无需任何 key。
- **没有配任何 key 时**：改用 ethan 内置 `image_search` 工具搜图并 `download=true`，把返回的本地路径直接写进对应页 JSON 的 `src`，跳过 gen_image.py。
- `--dry-run` 可先列出待解析项。

### Step 6：校验

```bash
python3 ~/.ethan/skills/ppt-generate/scripts/render_pptx.py /path/to/<项目目录> --check
```

- 有 error 必须修到 0 个再渲染；warning（越界/未知 textType 等）尽量修。报错信息里的 `slides[i]` 对应 `pages/` 下排序后的第 i 个文件，回到那一页改。

### Step 7：渲染

```bash
python3 ~/.ethan/skills/ppt-generate/scripts/render_pptx.py /path/to/<项目目录>
# 默认输出 <项目目录>/<项目名>.pptx；也可 -o 指定；--theme 可临时覆盖主题
```

- 首次运行会自动 `pip install python-pptx latex2mathml mathml2omml`（纯 Python 依赖）；用到 icon: 图标时还会自动装 `pymupdf`（SVG→PNG 光栅化）。

### Step 8：逐页复审，单页返修

渲染完**不要直接交付**。逐页过一遍复审清单，有问题的页**只改那一个 page 文件**再重新渲染（这就是项目制的意义）：

1. 每页 action title 都是观点句？有没有名词短语漏网？
2. 密度：每页 2-4 个区块、形态错开？有没有纯文字堆砌页或空洞页（<60 字）？
3. 衔接：锚点编号全 deck 一致？承上/启下钩子都兑现了？章节导航点逐页正确？
4. 视觉纪律：无越界/贴边、语义色一致、装饰语法统一？主色是否灰调雅致、大面积填充是否「深色字+浅色底」（白字深底只留给小徽章）？
5. 数据页有结论栏和来源行？公式符号逐一解释了？
6. **公式纪律**：grep 一遍页面 JSON 里的 `_k`、`√d_`、`\sqrt` 字面量——展示公式都走 latex 元素、行内变量都用 sub/sup run，没有裸文本伪公式？形状内嵌文本（圆圈/步骤条/按钮）都写了 `text.align: "middle"`？

- 若本机装了 LibreOffice（`soffice`），可 `soffice --headless --convert-to pdf <pptx>` 再 `pdftoppm -png` 逐页转图，用文件读取工具看图做视觉自检，溢出/重叠/字体替换问题一目了然；没有这些工具就按清单文字审查。
- 返修只动 `pages/` 下的单页文件，改完重跑 Step 7 即可（页少时秒级）。

### 交付

告知用户：pptx 路径、页数、design system 名称与要点、哪些图是占位图（若有）、项目目录位置（`pages/` 下单页 JSON 可改后重新渲染）、所有元素都能在 PPT 里直接二次编辑。

## 预设主题（快速兜底 / 定制起点）

| 主题 | 风格 | 适用 |
|---|---|---|
| `business-blue`（默认） | 白底商务蓝 | 汇报/总结/通用 |
| `dark-tech` | 深色科技 | AI/技术分享/发布会 |
| `fresh-green` | 清新绿 | 教育/环保/健康 |
| `vibrant-orange` | 活力橙 | 营销/活动/路演 |

正式 deck 应在预设基础上走 Step 2 定制（内联 theme 对象覆盖，结构见 schema.md 的 SlideTheme）。

## 关键约束（违反必然翻车）

1. **元素可编辑是底线**：禁止把整页渲染成一张大图；禁止 SVG path 形状（用预设形状名）；禁止 HTML 文本（用 runs）。
2. **gen:/icon: 占位符必须先跑 gen_image.py**，否则渲染器直接报错退出。
3. **中西文字体**：主题 `fontName`（中文）+ `latinFontName`（西文）分离设置；配对选择读 `references/fonts.md`。run 级显式 `fontName` 会同时覆盖中西文。
   - **渲染机不需要装字体**：渲染器只把字体名写入 pptx，字体解析发生在打开文件的机器上。
   - **查看端是 Linux（WPS/LibreOffice）时**：雅黑/Verdana 通常都没有，会被替换成默认字体。预先知道的话把主题改成 Linux 常见自带字体：中文 `Noto Sans CJK SC` / `WenQuanYi Micro Hei`，西文 `DejaVu Sans`。
4. **坐标纪律**：元素不越界（右 ≤940、下 ≤540）、不贴边、页边距 60/40；一行 item ≤38 字。
5. **图表用原生 chart 元素**（数据可编辑），不要用 image_search 找图表截图。
6. **演讲者备注**写进该页 JSON 的 `remark` 字段，不要塞进页面元素。
7. 项目目录整体交付与保留：`deck.json` + `pages/` + `assets/` 别删（用户可能改单页后重新渲染）；pptx 默认输出在项目目录内。

## 参考文档（按需 skill_read 加载）

- `references/schema.md` — deck/页 JSON 完整字段定义（写页前必读）
- `references/layout-guide.md` — 页面骨架、版式库、信息密度、衔接与设计语言规则
- `references/fonts.md` — 中西文字体配对与平台适配（Step 2 必读）
- `examples/demo.json` — 覆盖全部元素类型的示例 deck（单文件模式，可当元素写法参考）

## 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| 渲染报「图片占位符未解析」 | 跳过了 Step 5 | 跑 gen_image.py 或把 src 改成本地路径 |
| 渲染报「项目目录缺少 deck.json」 | deck 参数传了目录但没有元信息文件 | 在项目目录补 deck.json（version/canvas/theme） |
| 渲染报「页文件应为单个 Slide 对象」 | pages/*.json 里写成了数组或包裹层 | 每页文件直接是 `{"id","type","elements":[...]}` |
| pip 自动安装失败 | 无网络/权限 | `pip3 install --user python-pptx latex2mathml mathml2omml` 后重试 |
| 中文变方框/宋体 | 用户机器无该字体 | 换主题 fontName（Windows: 微软雅黑，macOS: PingFang SC），详见 fonts.md |
| Linux/WPS 打开字体被替换、版式跑偏 | Linux 无雅黑/Verdana | 主题改 `fontName: Noto Sans CJK SC`（或 WenQuanYi Micro Hei）+ `latinFontName: DejaVu Sans` 后重新渲染 |
| 公式变成一行源码文本 | latex 依赖缺失或语法错 | 看 stderr 的 [warn]，检查 LaTeX 语法（latex2mathml 子集） |
| Pexels 搜不到中文词 | API 对中文支持差 | gen: 后用英文搜索词 |
