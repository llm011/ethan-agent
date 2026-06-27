# 论文精读 Skill — 双路径设计(通用)

## 背景:为什么需要双路径

ethan-agent 框架**不支持工具返回图片给 LLM**:
- `file_read` 读 PNG 会变成乱码(强制 UTF-8 文本解码)
- `ToolResult.content` 是纯 `str`,没有携带 image 的字段
- provider 只把工具结果当纯文本传给 API,模型看不到图

所以"用多模态能力看图表/架构图"在当前框架下**无法由 agent 自己完成**。我们提供两条路:

**路 A(vision,精度高但不通用)**:脚本里调外部多模态 API,把 PNG 喂给 vision 模型,产出 5 维度 JSON。需要部署方自己配 vision API key。

**路 B(text,通用但精度有限)**:只用文字层 `text`(manifest.json 里每页的 `text` 字段),agent 直接读 JSON 分析。不依赖外部 API,但图表/公式只能靠文字层描述(有时会被拍平成乱序)。

## 路线选择(由 SKILL.md 的 system prompt 决定)

- 如果用户配了 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY` → LLM 走**路 A**,调用 `analyze_page_vision.py` 脚本,逐页看图
- 如果没配 vision API → LLM 走**路 B**,读 `manifest.json` 里的 `text`,逐页输出 5 维度 JSON

**进度机制(不改内核,通用)**:
- LLM **逐页调用 shell 工具**(路 A)或**逐页输出 JSON**(路 B)
- 每页一次 ToolEvent(start/done)+ LLM 文本"✓ 第 N 页完成"
- 前端能实时看到进度,不会以为程序卡死

## 路径细节

### 路径 A(vision)步骤

1. `fetch_paper.py` 拉 PDF → `pdf_path`
2. `extract_pages.py` 拆页 → `manifest.json`(含每页 `png` + `text`)
3. **逐页循环**(共 N 页):
   - LLM 调 `shell` 工具执行 `analyze_page_vision.py --page <N>`
   - 脚本读 `page_NNN.png` + `text`,调 vision API,产出 `analysis_page_NNN.json`
   - LLM 输出"✓ 第 N 页完成(共 M 页)"
4. `merge_analysis.py` 收拢 → `merged_analysis.json`
5. LLM 做 Reduce,输出最终报告

### 路径 B(text)步骤

1. `fetch_paper.py` 拉 PDF → `pdf_path`
2. `extract_pages.py` 拆页 → `manifest.json`(含每页 `text`)
3. **逐页循环**(共 N 页):
   - LLM 读 `manifest.json` 的 `pages[N-1].text`
   - LLM 直接输出该页的 5 维度 JSON(落盘到 `analysis_page_NNN.txt`)
   - LLM 输出"✓ 第 N 页完成(共 M 页)"
4. `merge_analysis.py` 收拢 → `merged_analysis.json`
5. LLM 做 Reduce,输出最终报告

## 关键差异

| 维度 | 路径 A(vision) | 路径 B(text) |
|---|---|---|
| 图表/架构图精度 | 高(模型直接看渲染图) | 低(依赖文字层,可能拍平/乱序) |
| 公式/表格精度 | 高(看原版排版) | 低(文字层常把公式变乱码) |
| 外部依赖 | 需要 vision API key | 无 |
| 网络开销 | 每页一次 API 调用(图+文) | 无额外网络调用 |
| 通用性 | 受限(需配 key) | 高(纯 agent 框架能力) |
| 进度可见性 | 高(每次 shell 调用一个 ToolEvent) | 高(每页输出一次 JSON + 文本) |

## SKILL.md 的改写要点

1. **检测环境变量**:在 SKILL.md 的 system prompt 里写"如果环境变量 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY` 存在,走路径 A;否则走路径 B"。

2. **明确逐页指令**:两条路都要写"**必须逐页处理,不要一次性处理所有页**。每处理完一页,输出进度文本:✓ 第 N 页完成(共 M 页)。"

3. **工具调用链路**:路径 A 要写"用 shell 工具调 `analyze_page_vision.py`";路径 B 要写"读 `manifest.json` 的 `text` 字段,输出 JSON 并落盘"。

4. **Reduce 阶段统一**:两条路的 Reduce 一样(读 `merged_analysis.json`,输出最终报告)。

## 部署建议

- 如果部署方有能力配 vision API → 推荐**路径 A**,精度高
- 如果部署方只想用 agent 框架自带模型 → 用**路径 B**,通用性强
- 两条路可以共存,让 LLM 自己根据环境变量选
