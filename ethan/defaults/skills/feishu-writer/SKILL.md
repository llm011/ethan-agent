---
name: feishu-writer
description: >
  TRIGGER WHEN: 用户要求"写飞书文档"、"生成研报"、"画架构图(Mermaid/PlantUML)"且明确指定输出到飞书时。
  专业的飞书文档生成与富文本写入，支持高质感排版、Mermaid 净化及分块长文写入。
  本技能是 lark-doc / lark-wiki 的"长文创作 + 富文本写入"补充，不重复 lark-doc 已有的通用文档操作。
metadata:
  requires:
    bins: ["python3"]
    secrets:
      - path: "~/.ethan/.secrets/my_feishu.json"
        fields: ["app_id", "app_secret"]
        description: "飞书自建应用凭证。文件格式：{\"app_id\":\"cli_xxx\",\"app_secret\":\"xxx\"}。缺省时脚本会以明确错误退出，绝不回退到硬编码。"
  relates:
    - skill: lark-doc
      scope: "通用文档 CRUD（fetch/create/update/media）。feishu-writer 不重复这些能力，只在需要 add_ons Mermaid 块、按文本定位移动图、转移所有权时介入。"
    - skill: lark-wiki
      scope: "知识空间节点管理。feishu-writer 写入完成后，若需挂到 Wiki 节点，转交 lark-wiki。"
    - skill: lark-shared
      scope: "认证与权限处理。当本技能脚本报权限错误时，转交 lark-shared 走 split-flow 授权。"
---

# 飞书高级写作助手 (Feishu Writer)

本技能用于生成极致专业、具有"人味"的飞书文档。

## 🧭 与 lark-doc / lark-wiki 的协作分工

| 场景 | 用谁 |
|------|------|
| 创建 / 读取 / 局部编辑普通文档 | `lark-doc`（`lark-cli docs +create/+fetch/+update`） |
| 知识空间节点管理、挂文档到 Wiki | `lark-wiki` |
| 复杂架构图（自由排版、SVG） | `lark-whiteboard`（`whiteboard +update`） |
| **原生 Mermaid add_ons 块注入（block_type=40）** | **本技能 `add_mermaid.py`** |
| **按正文文本定位 → 删除旧块 → 在锚点后插入新 Mermaid** | **本技能 `move_chart.py`** |
| **把文档所有权从 bot 转给用户** | **本技能 `transfer_owner.py`** |
| 长文方略、去 AI 味排版、黄金开局 | **本技能（写作规范）** |

**铁律**：本技能脚本是 lark-doc 的补充，不重新实现 `docs +create/+fetch/+update`。当用户的需求落在 lark-doc 已覆盖的通用操作上时，优先走 lark-doc；只有需要 add_ons Mermaid 块、按文本移动图、转移所有权时才用本技能脚本。

## 🛡️ 核心铁律 (Hardlines)

1. **去 AI 味排版**:
   - 严禁署名（如 "by AI"）。
   - 禁止在正文写进度信息。
   - 标题要么纯中文，要么纯英文，禁止中英混杂（机翻感）。
2. **黄金开局**: 必须采用"# 概述 -> ## 背景 -> ## 目标 (List)"的起手式。
3. **视觉纵深**:
   - 严禁扁平架构图。
   - **PlantUML 优先**：架构图优先使用 PlantUML。
   - **Mermaid 净化**：节点必须用双引号包裹 `A["节点名"]`，严禁包含斜杠或括号以防客户端崩溃。注入前必须剔除节点名中的 Emoji 和特殊符号。

## 🛡️ 核心工作流 (Workflow)

### 1. 规划阶段 (Planning)
- 超过 5000 字长文必须"分而治之"：先出提纲 -> 标注章节字数 -> 报备给凌总。

### 2. 写入阶段 (Execution)
- **分片注入**: 每 20 个 Block 切割一次进行插入（单次上限 50）。
- **原生表格**: 必须采用"原地 PATCH"法（读取 cell 内默认 block 并替换），严禁产生空行。
- **图片搬运**: 严禁复制旧文档的 Token。必须先 `download` 到本地再 `insert`。

## 🧰 脚本工具箱

所有脚本均从 `~/.ethan/.secrets/my_feishu.json` 读取飞书自建应用凭证（`app_id` / `app_secret`），**绝不硬编码**。文件格式：

```json
{ "app_id": "cli_xxxxxxxxxx", "app_secret": "xxxxxxxxxxxxxxxxxx" }
```

如果该文件缺失或字段不全，脚本会以非零退出码报错，不会回退到任何内置默认值。

### `scripts/add_mermaid.py` — 注入原生 Mermaid add_ons 块

将一段 Mermaid 代码作为 `block_type=40` 的 add_ons 块追加到指定文档末尾（或指定 index）。适合需要"原生 Mermaid 渲染"而非 SVG 画板的场景。

```bash
# 从 stdin 读 Mermaid，追加到文档末尾
python ~/.ethan/skills/feishu-writer/scripts/add_mermaid.py <doc_token> < mermaid.txt

# 或直接传字符串
python ~/.ethan/skills/feishu-writer/scripts/add_mermaid.py <doc_token> --mermaid 'graph TD\n  A["x"] --> B["y"]'

# 指定插入位置（默认 -1 末尾）
python ~/.ethan/skills/feishu-writer/scripts/add_mermaid.py <doc_token> --index 5 -m 'graph TD...'
```

**净化规则**：脚本不会替你净化 Mermaid。调用方必须保证节点名用双引号包裹、无斜杠/括号/Emoji。

### `scripts/move_chart.py` — 按文本定位移动图

按"正文片段"在文档中找到包含该文本的 block，记下其 index+1 作为插入点；删除指定的旧 block_id；在该位置插入新的 Mermaid add_ons 块。常用于"把底部的图挪到对应章节后面"。

```bash
python ~/.ethan/skills/feishu-writer/scripts/move_chart.py <doc_token> \
  --delete-block-id <block_id_to_remove> \
  --anchor-text "章节正文中的一段唯一文本" \
  --mermaid-file mermaid.txt
```

`--mermaid-file` 优先于 `--mermaid`；两者缺一回退到 stdin。

### `scripts/transfer_owner.py` — 转移文档所有权

把文档 owner 从当前持有者（通常是 bot）转给指定用户。先尝试 v1 接口，失败再尝试 v2。

```bash
python ~/.ethan/skills/feishu-writer/scripts/transfer_owner.py <doc_token> \
  --member-id <ou_xxxxx> --member-type openid
```

`--member-type` 默认 `openid`，可传 `userid` / `departmentid` 等。

## 避坑指南 (Gotchas)

- **字数幻觉 (Word Count Illusion)**: AI 一次性输出极难突破 3000 字（往往把 Token 数当成字数）。如果是 5000+ 字深度长文，必须采用"多轮迭代注入 (Multi-pass Expansion)"策略：先生成骨架，再逐个章节进行深度扩写代码和逻辑细节。
- **画板协议匹配 (Whiteboard API Integration)**: 当需要画出更复杂和自由排版的架构图时，**强烈推荐使用** `lark-whiteboard` 技能（`whiteboard +update`），通过 JSON DSL 或 Mermaid 代码导出 OpenAPI 格式后渲染，不要直接手写底层 OpenAPI。本技能的 `add_mermaid.py` 只用于"原生 add_ons Mermaid 块"这种轻量场景。
- **文档防碎裂 (Document Fragmentation)**: 多次向同文档注入时，必须用 `lark-cli docs +update --command overwrite` 全量覆盖或基于 Block ID 原地替换，严禁一味 append 导致结构崩塌。
- **AI 结构化废话**: 严禁使用"1. 执行摘要"、"总结"等 AI 惯用语，必须严格遵守"黄金开局"（# 概述 -> ## 背景 -> ## 目标）；去掉所有章节数字编号（如 `## 1.`），保持专业感。
- **429 频率**: 批量填表时必须 `time.sleep(0.5)`。
- **身份切换**: 必须强制使用 **User Token** 创建（`lark-cli docs +create --as user`），确保文档 Owner 是凌总而非机器人。如果文档已被 bot 创建，用本技能 `transfer_owner.py` 转给凌总。
- **Mermaid 崩溃**: 不要相信 API 返回的 Success，必须在注入前手动剔除节点名中的 Emoji 和特殊符号。
- **凭据安全**: 严禁把 `app_secret` 写进脚本或日志。所有脚本只从 `~/.ethan/.secrets/my_feishu.json` 读取，且打印日志时禁止输出 Authorization header 或 token 明文。

## 渐进式参考 (References)

- **长文方略**: （可选）`references/long-form.md` — 万字研报的撰写逻辑。本地暂未引入，需要时再从远端同步。
- **视觉模板**: （可选）`references/diagram-styles.md` — 莫兰迪色系配置。本地暂未引入。
