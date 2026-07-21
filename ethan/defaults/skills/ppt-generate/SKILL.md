---
name: ppt-generate
description: "从一句话/大纲/文档生成原生可编辑的 PPT（.pptx）。中间格式采用瘦身版 PPTist schema（JSON），渲染为 python-pptx 原生矢量元素——文本、形状、图表、表格、公式全部可在 PowerPoint/WPS 里二次编辑。当用户说「做PPT」「生成幻灯片」「写个汇报PPT」「把这份文档做成演示文稿」「pptx」「slides」「presentation」「课件」时触发。"
trigger: "PPT|ppt|pptx|幻灯片|演示文稿|slides|presentation|deck|做PPT|生成PPT|汇报PPT|课件|keynote"
version: 1.0.0
display_name: PPT 生成器
platforms: [macos, linux, windows]
metadata:
  openclaw:
    requires:
      bins:
        - python3
---

# PPT 生成器（PPTist schema · python-pptx 渲染）

把自然语言需求变成**原生可编辑**的 pptx：不是图片拼贴，每个文本框、形状、图表、表格、公式都是 PPT 原生元素，用户打开就能改。

## 工作流（严格按顺序）

```
需求 → ①大纲 → ②deck.json → ③gen_image.py 填图 → ④--check 校验 → ⑤render_pptx.py 渲染 → 交付
```

### Step 1：规划大纲

- 先输出大纲给用户（除非用户说直接生成）：每页定 `slideType`（cover/contents/transition/content/end）和核心内容。
- 页数：默认 5-8 页；用户没说要目录/过渡页就不加。

### Step 2：写 deck.json

- **Schema 全文见 `references/schema.md`**（元素字段、形状名表、主题结构），写之前必读。
- **排版坐标见 `references/layout-guide.md`**（各 slideType 的网格和字号纪律），避免贴边/溢出。
- 画布固定 1000×562.5；文本用结构化 runs，**不写 HTML**；形状只用预设名，**不写 SVG path**。
- 公式页用 `latex` 元素（OMML 原生公式，PPT 里可再编辑），不要画成图片。
- 图片先用占位符：
  - 照片/配图 → `"src": "gen:modern office skyline"`（英文搜索词效果更好）
  - 图标 → `"src": "icon:mdi:rocket-launch"`（Iconify 集合:名称，如 mdi/fa/carbon）
  - 用户提供的图 → 直接写本地路径
- 大 deck 分次写入再合并（单次响应 token 有限）：先写 cover+contents，再分批写 content 页。

### Markdown 输入约定（用户给 md 大纲时）

用户可能直接给一份详细的每页规划 md。按以下映射转成 deck.json：

```markdown
# PPT 主题：大模型时代的搜索架构
主题：dark-tech          ← 可选，映射 theme
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


### Step 3：填充图片

```bash
python3 ~/.ethan/skills/ppt-generate/scripts/gen_image.py /path/to/deck.json
```

- 瀑布流：Pexels（需 `PEXELS_API_KEY`）→ Unsplash（需 `UNSPLASH_ACCESS_KEY`）→ AI 生图（需 `ETHAN_IMAGE_GEN_API_KEY`）→ 纯色占位图（保底，永不失败）。
- Iconify 图标无需任何 key。
- **没有配任何 key 时**：改用 ethan 内置 `image_search` 工具搜图并 `download=true`，把返回的本地路径直接写进 deck.json 的 `src`，跳过 gen_image.py。
- `--dry-run` 可先列出待解析项。

### Step 4：校验

```bash
python3 ~/.ethan/skills/ppt-generate/scripts/render_pptx.py /path/to/deck.json --check
```

- 有 error 必须修到 0 个再渲染；warning（越界/未知 textType 等）尽量修。

### Step 5：渲染交付

```bash
python3 ~/.ethan/skills/ppt-generate/scripts/render_pptx.py /path/to/deck.json -o /path/to/输出.pptx
# 换主题：--theme dark-tech
```

- 首次运行会自动 `pip install python-pptx latex2mathml mathml2omml`（纯 Python 依赖）；用到 icon: 图标时还会自动装 `pymupdf`（SVG→PNG 光栅化）。
- 交付时告知：文件路径、页数、主题、哪些图是占位图（若有）、可以在 PPT 里直接改任何元素。

## 预设主题（deck 顶层 `"theme": "<名字>"`）

| 主题 | 风格 | 适用 |
|---|---|---|
| `business-blue`（默认） | 白底商务蓝 | 汇报/总结/通用 |
| `dark-tech` | 深色科技 | AI/技术分享/发布会 |
| `fresh-green` | 清新绿 | 教育/环保/健康 |
| `vibrant-orange` | 活力橙 | 营销/活动/路演 |

用户给了品牌色/风格描述时，内联一个 theme 对象覆盖（结构见 schema.md 的 SlideTheme）。

## 关键约束（违反必然翻车）

1. **元素可编辑是底线**：禁止把整页渲染成一张大图；禁止 SVG path 形状（用预设形状名）；禁止 HTML 文本（用 runs）。
2. **gen:/icon: 占位符必须先跑 gen_image.py**，否则渲染器直接报错退出。
3. **中文字体**：主题 `fontName` 默认 `Microsoft YaHei`；macOS 用户可建议换 `PingFang SC`。渲染器会同时设置 latin/ea 字体，中文不会变宋体。
4. **坐标纪律**：元素不越界（右 ≤940、下 ≤540）、不贴边、页边距 60/40；一行 item ≤38 字。
5. **图表用原生 chart 元素**（数据可编辑），不要用 image_search 找图表截图。
6. **演讲者备注**写进 slide 的 `remark` 字段，不要塞进页面元素。
7. 文件命名：输出到用户指定目录，默认 `~/Downloads/<主题>.pptx`；deck.json 与 .assets 目录放一起，别删（用户可能想重新渲染）。

## 参考文档（按需 skill_read 加载）

- `references/schema.md` — deck JSON 完整字段定义（写 deck 前必读）
- `references/layout-guide.md` — 各 slideType 的版式坐标与字数纪律
- `examples/demo.json` — 覆盖全部元素类型的示例 deck（可当模板改写）

## 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| 渲染报「图片占位符未解析」 | 跳过了 Step 3 | 跑 gen_image.py 或把 src 改成本地路径 |
| pip 自动安装失败 | 无网络/权限 | `pip3 install --user python-pptx latex2mathml mathml2omml` 后重试 |
| 中文变方框/宋体 | 用户机器无该字体 | 换主题 fontName（Windows: 微软雅黑，macOS: PingFang SC） |
| 公式变成一行源码文本 | latex 依赖缺失或语法错 | 看 stderr 的 [warn]，检查 LaTeX 语法（latex2mathml 子集） |
| Pexels 搜不到中文词 | API 对中文支持差 | gen: 后用英文搜索词 |
