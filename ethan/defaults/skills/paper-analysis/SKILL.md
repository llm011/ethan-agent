---
name: paper-analysis
description: 学术论文深度精读与 Map-Reduce 分析。当用户要求"精读论文"、"深度解读论文"、"分析论文"、"paper analysis"、"详细解读 arxiv 论文"时触发。脚本把 PDF 逐页拆成图+文(Map)，按 5 维度逐页精读(每页实时反馈进度)，再汇总整合(Reduce)输出完整解读。支持 PDF 链接、arXiv ID 或本地文件路径。
trigger: "精读论文|深度解读论文|解读论文|分析论文|paper analysis|论文精读|arxiv|arXiv|读这篇论文|map reduce 论文"
---

# Paper Analysis — 论文精读 Skill

把一篇论文做成结构化、有据可查的深度解读。核心是 **Map-Reduce + 脚本控制 PDF**:脚本负责把 PDF 变成「逐页图片 + 文字层」,逐页精读再汇总。**所有结论必须落到具体数字和具体引用,不许含糊。**

## 环境与脚本

PDF 处理脚本在 `scripts/` 下,位于用户 skills 目录 `paper-analysis/scripts/` 或包内 `ethan/defaults/skills/paper-analysis/scripts/`(两份内容一致,任取其一)。

| 脚本 | 作用 | 调用方式 |
|------|------|----------|
| `fetch_paper.py` | arXiv ID / URL / 本地路径 → 统一落地为本地 PDF(仅标准库,走 `HTTPS_PROXY`) | `shell: python scripts/fetch_paper.py "<source>" --out-dir ./paper_work` |
| `extract_pages.py` | PDF → 逐页 `page_NNN.png` + 文字层 + `manifest.json` | `shell: uv run --with pymupdf python scripts/extract_pages.py "<pdf>" --dpi 150` |
| `analyze_page_vision.py` | **【路径A】** 单页 PNG+文字 → 5维 JSON(脚本内调多模态 API) | `shell: uv run --with anthropic python scripts/analyze_page_vision.py "<manifest>" --page N` |
| `merge_analysis.py` | 收拢逐页 `analysis_page_NNN.json` → 一个数组,供 Reduce | `shell: python scripts/merge_analysis.py "<pages_dir>"` |

脚本约定:每个脚本 **stdout 末行打印一行 JSON**,解析它拿路径,不要去解析中间日志。

## 路径选择(关键)

本 skill 有两条路径,**逐页精读这步由环境决定**:

- **路径 A(vision,精度高)**:若已配置 `ANTHROPIC_API_KEY`(或 `ANTHROPIC_AUTH_TOKEN`)+ `ANTHROPIC_BASE_URL`,走这条。逐页调用 `analyze_page_vision.py`,脚本内把渲染图喂给多模态模型,能看清图表/架构图/公式。
  - 注意:agent 框架不支持把图片喂给 LLM(`file_read` 读 PNG 是乱码),所以"看图"必须由脚本内的 API 调用完成,不能让 agent 自己读图。
  - 中转网关踩坑:若报 `Your request was blocked`,是 WAF 拦 SDK 默认 UA,设 `ANTHROPIC_USER_AGENT=curl/8.4.0`;若报 524 超时,单页输出已控制 token,不会触发。

- **路径 B(text,通用)**:若没有 vision API 配置,走这条。只用 `manifest.json` 里每页的 `text` 字段(文字层),你(模型)直接读 JSON 逐页分析。无需额外 API,但图表/公式精度有限(文字层常把表格拍平、公式变乱码)。

**默认行为**:先检查 `ANTHROPIC_API_KEY` 环境变量是否存在 → 有则路径 A,无则路径 B。

## 工作流程

### 第 0 步:拿到 PDF + 拆页(两路共用)

```bash
# 用 shell 工具执行
python scripts/fetch_paper.py "2603.25737" --out-dir ./paper_work
# 解析末行 JSON 的 pdf_path
uv run --with pymupdf python scripts/extract_pages.py "<pdf_path>" --dpi 150
# 解析末行 JSON 的 manifest、pages 列表、num_pages
```

> 大论文(>40 页)先 `--max-pages 40` 跑主体,附录单独按需处理。

### Phase 1 — MAP(逐页精读)

**铁律:必须逐页处理,严禁一次性处理所有页。** 每处理完一页,立即输出一行进度文本:`✓ 第 N 页完成(共 M 页)`,然后处理下一页。这样用户能实时看到进度,不会以为程序卡死。

**总页数** = `manifest.num_pages`。

#### 路径 A(vision)— 逐页调脚本

对每一页 N(1..num_pages),用 `shell` 工具执行:

```bash
uv run --with anthropic python scripts/analyze_page_vision.py "<manifest_path>" --page N
```

脚本会读 `page_NNN.png` + 文字层,调多模态模型产出 `analysis_page_NNN.json`,末行打印 `{"page":N,"out":"...","chars":C}`。

每次调用就是一个独立的工具步骤(前端可见 start→done)。**每页调一次,不要并行/批处理**,确保进度逐页可见。

#### 路径 B(text)— 你自己逐页分析

读取 `manifest.json`,对每一页 N:

1. 拿到 `pages[N-1].text`(该页文字层)
2. 按 5 维度分析这一页(见下),**只输出该页涉及的维度,带原文数字**
3. 用 `file_write` 把结果存成 `<pages_dir>/analysis_page_NNN.txt`(或 .json)
4. 输出进度:`✓ 第 N 页完成(共 M 页)`

每页一次 `file_write` 调用 = 前端一个工具步骤,进度逐页可见。

### Phase 2 — REDUCE(汇总整合)

```bash
python scripts/merge_analysis.py "<pages_dir>"
# 末行 JSON 给出 merged 文件路径
```

用 `file_read` 读合并后的 `merged_analysis.json`,做深度整合:

- **合并同类项**:把散在各页的同主题内容聚到一处
- **去重精炼**:去重复,保留最准确的表述
- **数据统一**:所有实验数据整合成完整对比表
- **逻辑梳理**:创新点 → 实验验证的因果链清晰

**最终输出**(Reduce 阶段你自己流式输出,用户能逐字看到报告生成):

```
# <论文标题>
**arXiv: <编号>**

## 1. 执行摘要
## 2. 为什么重要
## 3. 前人工作(对比表)
## 4. 创新点(逐条 + 技术原理)
## 5. 实验结果(主结果表 + 消融表)
## 总体评价(创新性/实用性/严谨性打星 + 启发)
```

## 5 维度精读框架

每页按这 5 维度分析(详细 schema 见 [references/analysis-framework.md](references/analysis-framework.md)):

1. **论文式摘要** — 核心问题、解决方案、关键创新(1-3)、成果(必须有具体数字)
2. **为什么重要** — 核心痛点、真实场景需求、不解决的后果、一句话通俗总结
3. **前人工作** — 现有方法分类(2-4 流派)、代表论文、缺陷(带数据)、性能对比
4. **创新点** — 逐个列创新点、技术原理(通俗讲)、对比优势、核心架构(文字描述)
5. **实验结果** — 性能对比表、消融实验(每模块贡献度)、不同配置表现、3-5 个数据洞察

**不是每页五维全有**。某页只讲实验就只填维度 5,但该页涉及的维度必须填满、带原文数字。

## 使用示例

- "精读这篇论文 https://arxiv.org/abs/2603.25737"
- "深度解读 arxiv 2603.25737"
- "用 map reduce 分析这篇论文"

## 铁律

- 实验数据**必须有具体数字**:"提升明显" ❌ → "top-1 从 76.2% 提到 81.5%" ✅
- 创新点必须与技术细节一一对应
- 现有方法对比必须公正,**引用具体论文名/年份**
- 消融实验要分析**每个模块的独立贡献**
- **逐页处理,每页输出进度**,不要一次性跑完让用户以为卡死
- 路径 A 看不清的图/表,确认 `page_NNN.png` 存在再调脚本;路径 B 文字层乱码的公式/表格,诚实标注"文字层不可读,建议路径 A 重跑"

## 参考

- [references/analysis-framework.md](references/analysis-framework.md) — 5 维度 JSON schema + 填写铁律
- [references/dual-path-design.md](references/dual-path-design.md) — 双路径设计与取舍
