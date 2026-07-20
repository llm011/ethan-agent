---
name: paper-analysis
description: 学术论文深度精读与 Map-Reduce 分析。当用户要求"精读论文"、"深度解读论文"、"分析论文"、"paper analysis"、"详细解读 arxiv 论文"时触发。脚本把 PDF 逐页拆成图+文(Map)，按 5 维度逐页精读(每页实时反馈进度)，再汇总整合(Reduce)输出完整解读。支持 PDF 链接、arXiv ID 或本地文件路径。
trigger: "精读论文|深度解读论文|解读论文|分析论文|paper analysis|论文精读|arxiv|arXiv|读这篇论文|map reduce 论文"
license: MIT
version: 1.0.0
source: internal (hermes agent)
---

# Paper Analysis — 论文精读 Skill

把论文做成结构化、有据可查的深度解读。核心 **Map-Reduce + 脚本控制 PDF**:脚本拆页,逐页精读,汇总。**所有结论落到具体数字和引用,不许含糊。**

[CRITICAL — 触发本 skill 时,必须严格按下列流程用 `shell`/`file_write` 工具执行脚本完成精读,**禁止用 web_search/web_fetch 替代**(它们拿不到图表/公式)。]

## 脚本路径(重要,先确定)

脚本目录有两种可能,**开工前先用一次 `shell` 确定哪条存在**,后续命令统一用它:
```bash
ls ./ethan/defaults/skills/paper-analysis/scripts/ 2>/dev/null && echo USE_PKG || ls ~/.ethan/skills/paper-analysis/scripts/
```
- 输出含 `USE_PKG` → 脚本根 `SCRIPTS=./ethan/defaults/skills/paper-analysis/scripts`
- 否则 → 脚本根 `SCRIPTS=~/.ethan/skills/paper-analysis/scripts`

(下文统一写 `$SCRIPTS/xxx.py`;不要用 `fd_find` 满仓库找脚本。)

| 脚本 | 作用 |
|---|---|
| `fetch_paper.py` | arXiv ID/URL/本地路径 → PDF(仅标准库) |
| `extract_pages.py` | PDF → 逐页 PNG + `text/page_NNN.txt` + manifest.json(`uv run --with pymupdf`) |
| `analyze_page_vision.py` | 【路径A】单页 vision → 5维 JSON(脚本内调多模态 API,`uv run --with openai`) |
| `merge_analysis.py` | 收拢逐页 JSON → Reduce 输入 |
| `extract_paper_content.py` | 【路径C】PDF → 章节文本 + 图片(含语义命名) + 表格标题 + 公式行(`uv run --with pypdf,pillow`) |

脚本 **stdout 末行打印一行 JSON**,解析它拿路径,不要解析中间日志。

## 路径选择(关键)

- **路径 A(vision,精度高)**:环境变量 `VISION_API_KEY`(或 `OPENAI_API_KEY`)+ `VISION_BASE_URL` 存在 → 走这条。脚本把 PNG 喂多模态模型,能看清图表/公式/表格。先用 `shell: echo $VISION_API_KEY` 确认。
- **路径 B(text,通用)**:无 vision 配置 → 直接 `file_read` 脚本已落盘的每页文字 `text/page_NNN.txt`(见下),逐页分析。图表/公式精度有限(文字层常把表格拍平、公式变乱码),失真处诚实标注。
- **路径 C(结构化提取,辅助)**:可选预处理,与 A/B 不冲突。`extract_paper_content.py` 用 pypdf 把 PDF 拆成「章节文本 + 图片清单(含语义命名) + 表格标题 + 公式行」,适合需要快速定位「这张图在第几页」「这篇有几个公式」或单独抽图给用户看的场景。**注意**:pypdf 抽的公式是文字层片段,会丢上下标/特殊符号;表格只检测标题不含内容——要原貌仍需走路径 A 看 page_NNN.png。

## 路径 C 用法(可选,结构化提取)
```bash
uv run --with pypdf,pillow python $SCRIPTS/extract_paper_content.py "<pdf>"   # 解析末行 result_file / useful_images_dir / formulas_dir 等
```
末行 JSON 字段速查:`result_file`(完整汇总)、`useful_images`(有价值图片数,尺寸≥20×20)、`useful_images_dir`(语义命名,如 `Figure1_attention_useful.png`)、`tables`(检测到的 Table N 标题)、`formulas`(Equation N / 数学符号 / 等式行)、`sections`(按章节切分的全文)。
- 典型场景 1:用户问"这篇论文有哪些图" → 跑路径 C,`ls` useful_images_dir 给用户看。
- 典型场景 2:Reduce 阶段需要核对某公式原文 → `file_read` formulas_dir 下的 `pageN_formulaM.txt`。
- 典型场景 3:想快速读章节而不是逐页 → `file_read` result_file 的 `text.sections` 数组。
- **不要把路径 C 当 vision 的替代**——它给不出图表的视觉结构、表格的行列对应、公式的真实排版。需要看图必走路径 A。

## 工作流程

### 第 0 步:拿 PDF + 拆页
```bash
python $SCRIPTS/fetch_paper.py "<源>" --out-dir ./paper_work        # 解析末行 pdf_path
uv run --with pymupdf python $SCRIPTS/extract_pages.py "<pdf>" --dpi 150  # 解析末行 manifest、effective_pages、references_start_page、text_dir
```
脚本默认最多 30 页,自动检测 References 起始页。末行 JSON 的 **`effective_pages`** = 实际该精读的页数(含 References 起始页、封顶 30)。每页文字层已落盘到 **`text_dir/page_NNN.txt`**(路径 B 直接读)。

> **页数上限可调,不是写死的**:默认 30 只是速度与覆盖度的折中(逐页精读每页都要发请求、耗工具轮数)。读长综述/长论文时按需放宽:`--max-pages 60` 抬高上限,`--max-pages 0` 完全不封顶(处理全部正文页)。正文本身不足上限时,`effective_pages` 会自动取正文实际页数,不会硬凑。

### Phase 1 — MAP(逐页精读,**并行批处理**)

[CRITICAL — **只处理第 1 到 `effective_pages` 页**。`effective_pages` 已自动扣除 References 及之后、并封顶 `--max-pages`(默认 30)。**绝不要处理 `effective_pages` 之后的页**(那是参考文献/附录,精读无意义且会耗光工具迭代轮数导致没机会输出报告)。**总精读页数 = `effective_pages`,不是 `num_pages`!**]

**必须逐页,每页产出独立结果。** 每完成一批输出 `✓ 第 N1-N2 页完成(共 effective_pages 页)`。

**并行提速(关键,避免迭代耗尽)**:agent 工具执行器对**同一轮的多个 tool_call 用 asyncio.gather 并行执行**。**两条路径都要并行批处理**:
- 路径 A(vision):一轮发起 **2-3 个** `shell`(各带不同 `--page`,vision 请求重,批太大易触发网关限流)
- 路径 B(text):一轮发起 **4-5 个** `file_write`

路径 A — 每页一个 shell(一轮发起多个,各带不同 `--page`,并行):
```bash
uv run --with openai python $SCRIPTS/analyze_page_vision.py "<manifest>" --page N --timeout 120
```
脚本读 `VISION_BASE_URL`/`VISION_API_KEY`/`VISION_MODEL`,产出 `analysis_page_NNN.json`,末行 `{page,out,chars}`。**若连续报 503/超时(网关限流或端点不稳),立即转路径 B**(读文字层分析),不要在 vision 上耗轮数。

路径 B — 直接 `file_read` 拆页时已落盘的 **`<text_dir>/page_NNN.txt`**(仅 1..effective_pages),按 5 维分析,每页一个 `file_write` 存 `analysis_page_NNN.txt`,**一轮读/写多页**。`text_dir` 取自 extract_pages 末行 JSON(形如 `<pdf>_pages/text`)。**不要自己写 `python -c` 去拼 manifest 的 text 字段**——文字已按页落盘,直接读对应 txt 即可。

### Phase 2 — REDUCE(汇总)
```bash
python $SCRIPTS/merge_analysis.py "<pages_dir>"     # 末行 merged 路径
```
`file_read` 合并后的 `merged_analysis.json`,深度整合(合并同类项/去重/数据成表/创新点↔实验对应),**流式输出最终报告**:
```
# <标题>   **arXiv: <编号>**
## 1.执行摘要  ## 2.为什么重要  ## 3.前人工作(对比表)
## 4.创新点(逐条+技术原理)  ## 5.实验结果(主结果表+消融表)
## 总体评价(创新/实用/严谨打星 + 启发)
```

## 5 维度框架(每页按此分析,**只填该页涉及的维度,带原文数字**)
1. **摘要** — 核心问题/方案/关键创新(1-3)/成果(必须具体数字)
2. **为什么重要** — 痛点/真实场景/不解决后果/一句话通俗总结
3. **前人工作** — 2-4 流派,各带代表作+年份+缺陷(带数据)
4. **创新点** — 逐个:技术原理(通俗)/对比优势/架构(文字描述)
5. **实验** — 性能对比表(列全 baseline)/消融(每模块独立贡献)/3-5 洞察

## 铁律
- 实验数据**必须有具体数字**:"提升明显"❌ → "top-1 76.2%→81.5%"✅
- 创新点必须与实验一一对应;消融分析每模块独立贡献
- 路径 B 文字层失真的图/公式/表格,标注"文字层不可读,建议路径 A 重跑"
- 详细 5 维 schema 见 `references/analysis-framework.md`(可 `file_read`)
