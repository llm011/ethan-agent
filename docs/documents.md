# 文档库（Documents）

Agent 产出的文档（报告、整理、记录、笔记、汇总等）的统一落盘与浏览入口。

## 它解决什么问题

`deliver_file` 的 jail 只约束「home 或 /tmp」，具体路径由 Agent 临场决定，于是产出散落各处。
实测 sessions.db 里的 **57 个交付文件，只有 1 个仍存在**——48 个写在 `/tmp` 被系统清理：

| 类型 | 交付数 | 仍存在 |
|------|--------|--------|
| png | 33 | 0 |
| html | 7 | 0 |
| md | 7 | 1 |
| mp3 | 4 | 0 |
| zip | 3 | 0 |
| pptx / jpg / webp | 3 | 0 |

文档库把这批产出收拢到固定根目录，文件数与「文档」页展示一一对应。

## 目录约定

```
~/.ethan/documents/
├── work/coze/每日MR/2026-09-28-mr动态.md
├── life/
├── routine/
└── .library.json          ← 元数据：收藏 / 置顶 / 来源对话
```

- **根目录固定但按 profile 隔离**：`documents_root()` 优先读 `ETHAN_DOCUMENTS_DIR`（测试隔离用），
  否则走 `user_data_dir()/documents` —— 与 memory/knowledge/sessions 一致，命名 profile 下是
  `~/.ethan/profiles/<name>/documents`。default profile 下仍是 `~/.ethan/documents`（历史行为不变）。
- **分类由 Agent 自主决定**：给 `doc_save` 传相对分类路径即可，父目录自动创建。
- **文件树不维护索引表**，直接由文件系统推导。元数据只存附加信息（`favorite` / `pinned` /
  `session_id` / `message_id` / `title`），文件被外部删除时元数据自然失效，不会出现
  「索引与实际不一致」的漂移。
- 允许的扩展名（`DOC_EXTS`）：`.md` `.markdown` `.txt` `.html` `.htm` `.pdf` `.docx` `.csv` `.xlsx`。
  隐藏文件（`.` 开头，含 `.library.json` 本身）与空目录不在树里出现。

## 安全边界

`resolve_in_root()`（`ethan/documents/library.py`）是所有读写删的唯一入口，逐段
`sanitize_segment()` 后校验最终路径仍在根目录内。`../../etc/passwd`、`/etc/passwd`、
`work/../../../etc/passwd`、`..` 等输入都会被清洗回库内，不会逃逸。

> **为什么文档库不复用 `/files/*` 的 session grant 授权**：那条链路要求「该 session 交付过此文件」，
> 而文档库里的文件属于用户而非某个会话，且支持移动/重命名/删除。故走独立的根目录 jail 校验。
>
> ⚠️ 一个容易踩的坑：`doc_save` 的卡片由 `file_jail.build_file_card` 构建，而它的 jail 只放行
> **home 或 /tmp**。生产根目录 `~/.ethan/documents/` 在 home 下所以没问题；但若有测试或部署把
> `ETHAN_DOCUMENTS_DIR` 指到别处（如 pytest 的 `tmp_path`，实为 `/private/var/folders/...`），
> 卡片会**静默构建失败**，表现为「文件存了但没交付」。

## LLM 工具

| 工具 | 作用 |
|------|------|
| `doc_save` | 写入文档库并交付文件卡片（一次完成「落盘 + 交付」）。参数：`path`（相对分类路径）、`content`、`title`、`session_id` |
| `doc_list` | 列出文档库内容，支持 `prefix` 过滤，用于避免重复创建、在原文档上续写 |

两个工具都设了 `no_compress = True`——输出里的路径/清单要被模型逐字回传给 `file_read`，
压缩成散文摘要会让模型无法再操作。

`DocSaveTool.side_effect = True`（写文件有副作用），与 `file_write` 同款：三方渠道认主人后，
非主人会话会被 `ChannelGuardProvider` 直接拒绝。

### ⚠️ 可达性：两个必须同时满足的条件

`doc_save` 的存在意义是「别把产出丢到 /tmp」，而这要求**提示词讲到它**且**工具真在上下文里**。
两个条件最初都没满足，机制等于没生效：

1. **协议块要注入到两条 prompt 分支。** `<documents_protocol>` 由 `_documents_protocol()`
   （`ethan/core/system_prompt.py`）提供，fast 与 full 两条分支各 append 一次。它曾只写在
   `if fast:` 里 —— 走完整提示词的对话完全不知道 `doc_save` 存在。
2. **工具要在广播清单里。** `doc_save`/`doc_list` 必须同时出现在
   `routing.base_tools`（full 档）与 `routing.fast_base_tools`（fast 档）
   （`ethan/core/config.py`）。只 `registry.register()` 不广播，模型看不见也就调不到，
   只能退回 `file_write` 写 /tmp，问题原样复发。这与 `ui_card` 当初的坑同款。

`tests/test_documents_library.py` 里有对应回归测试（含「清单里的名字与注册名逐字一致」的
拼写校验——名字打错是静默失效）。

## HTTP API

见 [`docs/interface.md`](interface.md) 的端点表（`/documents/*`）。全部要求 Bearer 鉴权。

## Web UI

路由 `/documents`，侧边导航位于「记忆」下方。功能：

- 左侧文件树（目录可展开/收起，首次加载自动展开一级目录），顶部显示文件总数 + 搜索框
- **置顶区**（可折叠）与**收藏区**分列于树上方；行内 hover 显示置顶/收藏/定位/删除按钮
- 点击文档在右侧预览（复用文件卡片同样的 markdown 渲染链路）
- **放大阅读**：隐藏列表区让正文占满宽度，侧边导航保留；放大态在正文头部补一个「返回」按钮
- **来源对话**：`session_id` + `message_id` → 跳 `/chat/<session_id>?msg=<message_id>` 定位到
  产出该文档的那条消息

Web 与 Desktop 两端同源（`web/components/documents-view.tsx` 与
`desktop/src/components/documents-view.tsx`；`lib/api-documents.ts` 只差 `API_URL` 常量与
`getApiUrl()` 函数）。Desktop 另在 `use-deep-link.ts` 注册了 `ethan://documents`。

## 迁移已有文档

历史产出散落在各处，不要盲目搬迁：

- **Obsidian vault 里的文档不要动**：若知识库后端配的是 `knowledge.backend: obsidian`
  （vault 如 `~/Documents/obsidian/work`），那些 md 是知识库的正常存储，不是孤儿产出。
- **只有「已交付给用户、但文件已消失」的才算孤儿**。可以查 `sessions.db` 的 `messages.cards`
  列（`type: "file"`）比对磁盘是否存在。
- 正文能否找回取决于它是否还在会话库里。`tool_steps` 的 `args` 经 `_format_args`
  （`ethan/core/tool_format.py`）截断为「前 100 字符 + … + 后 40 字符」，长文档的正文**不会**
  完整留存，无法据此恢复。

迁移一个文件并同步引用的流程（引用落在 `messages.cards`，它同时是 `/files/*` 的下载授权来源）：

1. 拷进文档库：`shutil.copy2` 到 `resolve_in_root(<分类路径>)`
2. 写元数据：`Library().update(rel, title=..., session_id=..., message_id=...)`
3. 改引用：把该消息 `cards` 里对应卡片的 `path` 换成新绝对路径（按主键 `UPDATE messages SET cards=? WHERE id=?`，
   不要整表重写）
4. 校验：新路径须过 `file_jail.resolve_jailed` 且扩展名在 `DELIVER_EXTS`，否则卡片点不动

<!-- auto-merge push-trigger 验证：本 PR 用用户 token 开启 auto-merge，
     验证合并后 push 工作流是否触发（对照 461fc053 的 0 次触发）。 -->

<!-- PAT 实验：用用户 token 开启 auto-merge，验证合并者身份与事件派发 -->
