# 知识库设计文档

## 概述

知识库让 Agent 能够存储和检索用户积累的笔记、参考资料、决策记录等信息。与短期的工作记忆不同，知识库条目由用户或 Agent 主动写入，永久保留，支持关键词和语义两种检索方式。

知识库采用**多后端抽象架构**：上层工具接口统一，底层存储可在本地 Markdown、Obsidian Vault、外部 REST API 之间切换。

---

## 架构

```
用户 / Agent
    │
    ▼
KnowledgeAddTool / KnowledgeSearchTool    ← LLM 直接调用
    │                                     （ethan/tools/builtin/knowledge.py）
    ▼
Registry (get_knowledge_backend)          ← 工厂函数，根据 config 选择后端
    │                                     （ethan/knowledge/registry.py）
    ▼
┌───────────────────────────────────────────────────────┐
│              KnowledgeBase (ABC)                       │
│                                                       │
│  ┌─────────────────┐  ┌──────────────────────┐       │
│  │ Filesystem (默认) │  │ Obsidian Vault       │       │
│  │ ~/.ethan/knowledge│  │ 用户指定 vault path   │       │
│  │ *.md             │  │ YAML frontmatter     │       │
│  └─────────────────┘  └──────────────────────┘       │
│                                                       │
│  ┌──────────────────────┐                             │
│  │ External REST API    │                             │
│  │ 第三方知识库/API      │                             │
│  └──────────────────────┘                             │
└───────────────────────────────────────────────────────┘
    │
    └─ VectorStore（sqlite-vec）   ← 向量索引（Filesystem/Obsidian 共用）
           ~/.ethan/memory/vectors.db
```

---

## 后端选择

在 `~/.ethan/config.yaml` 中配置：

```yaml
tools:
  knowledge:
    backend: filesystem        # "filesystem" | "obsidian" | "external"
    obsidian_vault_path: ""    # backend=obsidian 时必填，vault 根目录绝对路径
    obsidian_folder: "Knowledge"  # vault 内知识库子目录（"." 表示根目录）
    external_base_url: ""      # backend=external 时必填
    external_api_key: ""       # backend=external 时必填
```

### Filesystem（默认）

- 存储路径：`~/.ethan/knowledge/*.md`
- 无需额外配置，开箱即用
- 格式：`# 标题\ntags: a, b\n\n正文`

### Obsidian Vault

- 要求目标路径是合法的 Obsidian vault（含 `.obsidian/` 目录）
- 格式：YAML frontmatter + Markdown 正文
- 支持递归扫描子目录（`rglob("*.md")`）
- 写入格式示例：

```markdown
---
title: 笔记标题
tags:
  - python
  - async
---

# 笔记标题

正文内容
```

### External REST API

- 通过 HTTP 调用外部知识库服务
- 需配置 `base_url` 和 `api_key`
- 接口约定：`GET /search?q=&limit=`、`POST /items`、`GET /items/{id}`、`DELETE /items/{id}`

---

## 连通性校验

每个后端实现 `health_check() -> tuple[bool, str]` 方法：

| 后端 | 校验内容 |
|------|---------|
| Filesystem | 目录是否存在且可访问 |
| Obsidian | vault 路径存在 + `.obsidian/` 目录存在 + knowledge folder 存在 |
| External | HTTP GET `{base_url}/health` 返回 200 |

设置页面提供 `POST /settings/knowledge/validate` 端点，允许用户在切换后端时实时验证连通性。

---

## 存储格式

### Filesystem 格式

每个条目存为一个 Markdown 文件，文件名由标题自动 slugify 生成：

```markdown
# 笔记标题
tags: python, async, 备忘

正文内容，支持完整 Markdown 格式。
```

文件命名示例：`python-asyncio-备忘.md`，遇到同名自动加 `-1`、`-2` 后缀。

### Obsidian 格式

使用 YAML frontmatter（兼容 Obsidian Properties）：

```markdown
---
title: 笔记标题
tags:
  - python
  - async
---

# 笔记标题

正文内容
```

---

## 两种检索模式

### 关键词检索（keyword）

对标题、内容、tags 做词频打分，按命中词数排序。无需预先生成 embedding，速度快。

```python
kb.search("Python asyncio", limit=5)
```

### 语义检索（semantic）

基于 `sqlite-vec` 向量相似度（余弦距离）。写入时自动生成 512 维 embedding，查询时向量化后做 ANN 检索。

```python
await kb.semantic_search("异步编程最佳实践", limit=5)
```

**Embedding 引擎**：BGE-small-zh-v1.5 INT8 ONNX（24MB，中文专项优化，512 维）。
- 优先使用 BGE（装 `pip install 'ethan-agent[embedding]'` 后自动启用）
- 未安装时回退到内置 char n-gram 特征哈希 embedding（同为 512 维，schema 不变）

---

## LLM 工具

### `knowledge_search`

文件：`ethan/tools/builtin/knowledge.py`

在知识库中搜索相关条目（返回标题/摘要列表，含 source 路径）。Agent 会在使用 `web_search` 之前先查知识库，优先使用用户已记录的信息。

```python
knowledge_search(query="HA REST API 地址", limit=3)
```

### `knowledge_read`

文件：`ethan/tools/builtin/knowledge.py`

按 source 读取某一条的完整内容（标题/标签/正文全文）。`knowledge_search` 只返回摘要列表，需要看某条全文（或在编辑前先读全文）时用它。

```python
knowledge_read(source="/Users/x/.ethan/knowledge/ha-rest-api.md")
```

### `knowledge_add`

文件：`ethan/tools/builtin/knowledge.py`

将笔记、参考资料**新建**到知识库。同时写入 Markdown 文件和向量索引。

```python
knowledge_add(
    title="HA REST API 地址",
    content="Home Assistant 的 REST API 地址是 http://192.168.1.x:8123，token 在长效 token 管理页生成。",
    tags=["home-assistant", "api", "地址"]
)
```

### `knowledge_edit`

文件：`ethan/tools/builtin/knowledge.py`

编辑**已有**条目而非新建，解决「在同一条笔记/知识里追加或修改」每次都新建文档的问题：

- `mode=append`（默认）：把 `content` 追加到原正文末尾（中间空行分隔），保留原标题/标签。适合「再记一条 / 补充一点」。
- `mode=replace`：整篇替换正文；`title`/`tags` 不传则沿用原值。适合修订。

`source` 用 `knowledge_search` 结果里的路径；不确定原文时先 `knowledge_read` 看全文。写入后会重建该条的向量索引。

```python
knowledge_edit(source="...ha-rest-api.md", content="补充：token 有效期 10 年", mode="append")
knowledge_edit(source="...ha-rest-api.md", content="修订后的完整正文", mode="replace")
```

---

## HTTP API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/knowledge` | 列出所有条目，支持 `q` 参数关键词过滤，`mode=keyword\|semantic` |
| POST | `/knowledge` | 新增条目（`title`、`content`、`tags`） |
| PUT | `/knowledge/{source}` | 更新指定条目（按文件路径） |
| DELETE | `/knowledge/{source}` | 删除指定条目（同时清理向量索引） |
| GET | `/knowledge/search` | 语义检索，参数 `q`、`limit`、`semantic=true\|false` |
| POST | `/settings/knowledge/validate` | 校验当前后端连通性（body: `{backend, obsidian_vault_path, ...}`） |

### 新增条目

```bash
curl -X POST http://localhost:8900/knowledge \
  -H "Content-Type: application/json" \
  -d '{"title": "部署 checklist", "content": "1. 运行测试\n2. 检查 diff\n3. 更新文档", "tags": ["deploy"]}'
```

### 语义检索

```bash
curl "http://localhost:8900/knowledge/search?q=部署流程&limit=5&semantic=true"
```

### 校验后端连通性

```bash
curl -X POST http://localhost:8900/settings/knowledge/validate \
  -H "Content-Type: application/json" \
  -d '{"backend": "obsidian", "obsidian_vault_path": "/Users/x/Documents/obsidian/work", "obsidian_folder": "."}'
```

---

## Web UI

知识库页面（`/knowledge`）提供：

- 全部条目列表，支持关键词搜索
- 点击条目查看完整内容（Markdown 渲染）
- 编辑、删除现有条目
- 手动新增条目

---

## 设置项

在设置页面（`/settings`）中，知识库后端配置包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `tools.knowledge.backend` | choice | 后端选择：filesystem / obsidian / external |
| `tools.knowledge.obsidian_vault_path` | str | Obsidian vault 根目录绝对路径 |
| `tools.knowledge.obsidian_folder` | str | vault 内知识库子目录名（默认 Knowledge，"." 为根目录） |
| `tools.knowledge.external_base_url` | str | 外部知识库 REST API 的 base URL |
| `tools.knowledge.external_api_key` | str | 外部知识库认证 key |

切换后端时，UI 会调用 `/settings/knowledge/validate` 校验连通性，通过后才保存。

---

## Obsidian CLI 增强（可选插件）

Obsidian 后端默认使用纯文件系统操作（`rglob`、`open`），无需额外依赖即可工作。安装 **Obsidian CLI** 后可获得更快的搜索和标签管理能力，但**不安装也完全不影响基本功能**。

### 工作原理

```
ObsidianKnowledgeBase
    │
    ├─ CLI 可用？  → obsidian search / obsidian tags counts  (索引搜索，更快更准)
    │
    └─ CLI 不可用？→ 纯文件系统遍历 + 关键词匹配  (兜底，始终可用)
```

启动时自动通过 `shutil.which("obsidian")` 检测 CLI 是否在 PATH 中，无需手动配置。

### 安装方式

通过 Ethan 插件系统一键引导：

```bash
ethan plugin add obsidian-cli
```

该命令会：
1. 检测 `obsidian` 命令是否已在 PATH 中
2. 如果未找到，提示安装步骤（见下文）
3. 安装完成后，显示配置提示

#### 手动安装步骤

Obsidian CLI 是 Obsidian 桌面端（v1.12+）自带的功能，需在 app 内开启：

1. 确保 Obsidian 桌面版 ≥ v1.12
2. 打开 **Settings → General → Command line interface**
3. 点击 **Register** 注册 CLI 到系统 PATH
4. 验证：`obsidian --version`

> macOS 用户也可通过 Homebrew：`brew install --cask obsidian`（安装 app 后仍需在 app 内注册 CLI）

### 配置

**无需额外配置**。只要 `obsidian` 命令在 PATH 中可被发现，知识库后端就会自动使用 CLI 加速。

如果你希望显式禁用 CLI（强制走文件系统兜底），当前无独立开关——移除 PATH 中的 `obsidian` 命令即可。

### CLI 提供的能力

| 操作 | CLI 命令 | 对应方法 |
|------|---------|---------|
| 搜索笔记 | `obsidian search query=<keyword> --json` | `ObsidianKnowledgeBase.search()` |
| 标签统计 | `obsidian tags counts --json` | `ObsidianKnowledgeBase.list_tags()` |
| 创建笔记 | `obsidian create <path> --content "..."` | 预留，暂走文件系统 |
| 反向链接 | `obsidian backlinks <note>` | 预留 |

### 兜底策略

所有 CLI 操作都有文件系统兜底：

- **CLI 不存在**：启动时 `shutil.which("obsidian")` 返回 None → 全程走文件系统
- **CLI 存在但执行失败**（超时、返回非 0、JSON 解析失败）→ 自动 fallback 到文件系统方法
- **兜底搜索**：遍历所有 `.md` 文件，对标题+内容+标签做词频匹配
- **兜底标签**：遍历所有文件的 frontmatter `tags:` 字段统计

这意味着：
- 新用户无需关心 CLI → 文件系统兜底保证开箱即用
- 进阶用户安装 CLI → 自动获得性能提升，零配置

---

## 与记忆系统的区别

| 维度 | 知识库 | 工作记忆（Facts） |
|------|--------|-----------------|
| 写入方式 | 用户/Agent 主动调用工具 | 后台压缩自动提炼 |
| 内容类型 | 任意长度笔记、参考资料、文档 | 简短的事实条目（一句话） |
| 检索方式 | 关键词 + 语义向量检索 | 置信度排序后注入 prompt |
| 存储位置 | 取决于后端配置 | `~/.ethan/memory/memory.db` |
| 是否注入 prompt | 不自动注入，由 Agent 主动检索 | 自动注入 top-15 |

---

## 文件索引

| 文件 | 说明 |
|------|------|
| `ethan/knowledge/base.py` | KnowledgeBase ABC + Filesystem/Obsidian/External 三个实现 |
| `ethan/knowledge/registry.py` | 工厂函数，根据 config 选择并缓存后端实例 |
| `ethan/knowledge/__init__.py` | 模块导出 |
| `ethan/tools/builtin/knowledge.py` | LLM 工具（search / add / edit / read） |
| `ethan/core/config.py` | KnowledgeConfig 模型定义 |
| `ethan/core/config_schema.py` | 暴露知识库设置字段给 UI |
| `ethan/interface/routers/settings.py` | `/settings/knowledge/validate` 校验端点 |
| `ethan/interface/routers/knowledge.py` | HTTP API 路由 |
| `ethan/memory/vector_store.py` | sqlite-vec 向量存储 |
| `ethan/memory/embeddings.py` | Embedding 生成（BGE-small-zh INT8 / n-gram 回退） |
| `~/.ethan/knowledge/` | Filesystem 后端条目存储 |
| `~/.ethan/memory/memory.db` | 向量索引（SQLite） |
