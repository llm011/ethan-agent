---
name: obsidian
title: Obsidian Vault Manager
description: Read, search, create, and edit notes in the Obsidian vault.
version: 1.1.0
author: NousResearch
license: MIT
platforms: [linux, macos, windows]
trigger:
  - obsidian
  - Obsidian
  - ob笔记
  - 笔记
  - vault
  - 知识库笔记
  - wikilink
  - note
  - 读笔记
  - 写笔记
  - 搜索笔记
  - 记笔记
  - 存笔记
  - 保存笔记
  - 整理笔记
  - 标签
  - tag
  - 打标签
  - 加标签
  - 双链
  - backlink
  - frontmatter
  - 属性
  - canvas
  - 画布
  - daily note
  - 日记
  - 重命名笔记
  - 知识管理
---
# Obsidian Vault

Use this skill for filesystem-first Obsidian vault work: reading notes, listing notes, searching note files, creating notes, appending content, adding wikilinks, managing tags, maintaining backlinks, and editing frontmatter.

## 🚫 硬规则（必须遵守，不可绕过）

### R1：写入笔记只用 knowledge_* 工具

所有写入 Obsidian 笔记的操作，必须通过 `knowledge_add` / `knowledge_edit` 完成。

- ❌ 禁止 `file_write` 直接写 markdown 文件
- ❌ 禁止 `shell` 的 `mkdir` / `cat` / `echo` / `python3 -c "open(...).write(...)"`
- ❌ 禁止自己拼接 vault 路径——路径由后端按 scene 自动管理（`<vault>/<scene>/<slug>.md`）
- ✅ 新建 → `knowledge_add(title, content, tags, scene, frontmatter)`
- ✅ 追加 → `knowledge_edit(source, content, mode="append", scene)`
- ✅ 整篇替换 → `knowledge_edit(source, content, mode="replace", scene, frontmatter)`

**判断标准**：只要写入的内容是笔记/资料/纪要/PRD/设计文档等知识库条目（即使已经用 lark-cli / web_fetch 拉取了原文），写回时也必须走 knowledge_* 工具。

**为什么**：knowledge_* 工具会自动加 frontmatter（title/type/tags/created/updated，由 `yaml.safe_dump` 安全生成）、自动建子目录、自动建索引支持全文搜索；file_write 直写会绕过这一切，导致路径平铺根目录、frontmatter 字段缺失、搜索查不到。

### R2：内容来自外部文档/链接时，frontmatter={"source": ...} 必传

凡是笔记内容派生自外部网页/飞书文档/链接（用户提供了 URL，或你用 lark-cli / web_fetch 拉取过原文），调用 `knowledge_add` / `knowledge_edit` 时必须传 `frontmatter={"source": "{原始 URL}"}`。

- 固定字段（`title` / `type` / `tags` / `created` / `updated`）由后端自动管理，**不要**在 frontmatter 里重复传
- `type` 由 `tags[0]` 自动推断，无需手动指定
- 可按需追加 `author` / `published` 等扩展字段

### R3：scene 按场景区分

| 内容类型 | scene | 示例 |
|---|---|---|
| 工作向记录 | `work` | PRD、设计文档、会议纪要、技术方案、工作沉淀 |
| 个人/生活向 | `life` | 个人学习、生活记录、家庭事项 |
| 不确定 | `work` | 默认 work，用户明确说生活类时切 life |

scene 决定子目录（`<vault>/work/...` vs `<vault>/life/...`），不传 scene 会平铺到 vault 根目录——这是禁止的。

## Vault path

Use a known or resolved vault path before calling file tools.

The documented vault-path convention is the `OBSIDIAN_VAULT_PATH` environment variable, for example from `${ETHAN_HOME:-~/.ethan}/.env`. If it is unset, fall back to `~/Documents/obsidian/work`, then `~/Documents/Obsidian Vault`.

File tools do not expand shell variables. Do not pass paths containing `$OBSIDIAN_VAULT_PATH` to `read_file`, `write_file`, `patch`, or `search_files`; resolve the vault path first and pass a concrete absolute path. Vault paths may contain spaces, which is another reason to prefer file tools over shell commands.

If the vault path is unknown, `terminal` is acceptable for resolving `OBSIDIAN_VAULT_PATH` or checking whether the fallback path exists. Once the path is known, switch back to file tools.

## Read a note

Use `read_file` with the resolved absolute path to the note. Prefer this over `cat` because it provides line numbers and pagination.

## List notes

Use `search_files` with `target: "files"` and the resolved vault path. Prefer this over `find` or `ls`.

- To list all markdown notes, use `pattern: "*.md"` under the vault path.
- To list a subfolder, search under that subfolder's absolute path.

## Search

Use `search_files` for both filename and content searches. Prefer this over `grep`, `find`, or `ls`.

- For filenames, use `search_files` with `target: "files"` and a filename `pattern`.
- For note contents, use `search_files` with `target: "content"`, the content regex as `pattern`, and `file_glob: "*.md"` when you want to restrict matches to markdown notes.

## Create a note

调用 `knowledge_add` 工具创建笔记。**不要**用 `write_file` / `shell` / `file_write` 直写文件——见上方硬规则 R1。

```
knowledge_add(
    title="笔记标题",
    content="Markdown 正文（不要带 frontmatter，后端自动生成）",
    tags=["work/coze", "work/prd"],   # 第一个 tag 自动成为 type
    scene="work",                     # 必传，决定子目录
    frontmatter={"source": "https://...原始 URL..."}  # 来自外部链接时必传 R2
)
```

后端会自动：
- 生成 frontmatter（`title` / `created` / `updated` / `type` / `tags`），用 `yaml.safe_dump` 安全序列化
- 写到 `<vault>/<scene>/<slug>.md`（slug 由标题小写化生成，重名追加 `-1`/`-2`）
- 建立全文搜索索引

### 内容质量要求

写入 Obsidian 的内容必须遵循以下原则：

1. **内容完整性**：不要只保存摘要或片段，尽量保留原始内容的完整信息（正文、代码块、表格、列表等）。如果来源是网页或文档，应提取全部有价值内容。特别是**飞书文档**，必须调用 lark-doc 技能的 `scripts/fetch_doc.py` 脚本获取完整 Markdown 内容，不要仅凭记忆或摘要转写。
2. **格式规范**：使用标准 Markdown 格式，确保标题层级清晰、代码块有语言标识、列表缩进正确、表格对齐。飞书的 `<blockquote>` / `<cite>` / `<colgroup>` 等专有标签需在写入前清理为标准 Markdown（`>` / `[[wikilink]]` / 标准 table）。
3. **图片本地化**：笔记中引用的图片**必须先下载到 vault 的 `assets/` 目录**，然后使用相对路径或 wikilink 引用，不要直接引用外部 URL。
   - 下载路径：`<vault>/assets/<有意义的文件名>.png`（按内容命名，避免随机串）
   - 引用方式：`![[assets/my-image.png]]` 或 `![描述](assets/my-image.png)`
   - 如果图片无法下载（需认证、已失效等），保留原始 URL 并加注释标记 `<!-- 图片未下载: <url> -->`

## Append to a note

调用 `knowledge_edit(source, content, mode="append", scene)` 追加内容。`source` 是笔记的 slug 或绝对路径（之前 `knowledge_add` 的返回值）。

- ✅ 追加 → `knowledge_edit(source, content, mode="append", scene)`
- ✅ 整篇替换 → `knowledge_edit(source, content, mode="replace", scene, frontmatter)`
- ❌ 不要用 `read_file` + `write_file` 拼接整篇内容
- ❌ 不要用 `shell` 的 `echo >>` 追加

`mode="replace"` 会保留原文件的 `created` 字段，只刷新 `updated` 为今天。

## Targeted edits

定向修改用 `knowledge_edit(source, content, mode="replace", scene)` 整篇替换。当前 `knowledge_edit` 不支持局部 patch，需要修改局部内容时：先 `knowledge_read(source)` 读全文 → 在内存里改 → `knowledge_edit(source, modified_content, mode="replace", scene)`。

## Wikilinks

Obsidian links notes with `[[Note Name]]` syntax. When creating notes, use these to link related content.

- `[[Note Name]]` — link to a note
- `[[Note Name|Display Text]]` — custom display text
- `[[Note Name#Heading]]` — link to a heading inside a note
- `[[Note Name#^block-id]]` — link to a block reference
- `![[Note Name]]` — embed a full note
- `![[image.png]]` — embed an image attachment
- `![[image.png|300]]` — embed an image with a width hint

**正文链接规范**：如果文档中提到了已有的其他笔记或项目，使用 `[[双链]]` 将它们关联起来（例如：关于 AB 灰度配置，可参考 `[[AB 实验灰度方案]]`）。原始链接（如飞书文档 URL）应写入 frontmatter 的 `source` 字段。

## Frontmatter / Properties

笔记的 frontmatter 由 `knowledge_add` / `knowledge_edit` 后端自动生成，**不要**在 `content` 里手写 frontmatter 块。后端用 `yaml.safe_dump` 安全序列化，避免引号/冒号/反斜杠导致的解析错误。

### 自动生成的字段（不要手动传）

| 字段 | 来源 | 说明 |
|---|---|---|
| `title` | `knowledge_add(title=...)` | 笔记标题，引号风格由 yaml.safe_dump 按内容自动决定 |
| `created` | 后端 | 首次创建时设为今天；`knowledge_edit(mode=replace)` 时从原文件保留 |
| `updated` | 后端 | 每次写入刷新为今天 |
| `type` | `tags[0]` 自动推断 | 不要手动传，传了也会被忽略 |
| `tags` | `knowledge_add(tags=[...])` | 层级标签列表 |

### 扩展字段（通过 frontmatter 参数传入）

| 字段 | 何时传 | 示例 |
|---|---|---|
| `source` | 内容来自外部 URL 时必传（R2） | `frontmatter={"source": "https://..."}` |
| `author` | 需要记录作者时 | `frontmatter={"author": "张三"}` |
| `published` | 需要记录发布时间时 | `frontmatter={"published": "2026-07-15"}` |

### 标签（Tags）规范

**层级格式**：使用 `分类/子分类` 格式，支持多级嵌套，方便在 Obsidian 中折叠和检索。

常用标签体系：
- `work/<项目名>` — 项目归属（如 `work/coze`、`work/lark`）
- `tech/<技术栈>` — 技术研究（如 `tech/electron`、`tech/mcp`）
- `work/prd` — PRD / 设计案（type 自动推断为 `prd`）
- `work/tech-design` — 技术方案（type 自动推断为 `tech-design`）
- `work/meeting` — 会议纪要（type 自动推断为 `meeting`）
- `work/reference` — 参考资料（type 自动推断为 `reference`）
- `work/todo` — 个人待办
- `life/<分类>` — 生活类内容

**规则**：
- YAML 中的标签**不加** `#` 号；正文中的 inline 标签**必须**以 `#` 开头
- 创建新标签前，先运行 `tag_manager.py list` 查询已有标签，优先复用
- 合法字符：字母、数字、`_`、`-`、`/`；不以数字开头

To update frontmatter on an existing note: 调用 `knowledge_edit(source, content, mode="replace", scene, frontmatter={...})` 整篇替换，frontmatter 参数里只传扩展字段（如 `source`），固定字段（`title` / `type` / `tags` / `created` / `updated`）由后端管理。不要用 `read_file` + `patch` 改 frontmatter——这会绕过 yaml.safe_dump，可能产出非法 YAML。

## Tag Management

Tags use the `一级/二级/三级` hierarchical format. Reuse existing tags whenever possible; do not invent new top-level tags impulsively.

- **List existing tags**: `python3 ~/.ethan/skills/obsidian/scripts/tag_manager.py list` — scans frontmatter `tags:` fields and inline `#tag` occurrences across the vault.
- **Add a tag to a note**: `python3 ~/.ethan/skills/obsidian/scripts/tag_manager.py add "note_path.md" "project/active"` — patches the note's frontmatter (creates one if missing). `note_path` may be absolute, or relative to the vault root.
- **Tag format**: `alpha/beta/gamma`, supports unlimited nesting. No leading digits; allowed chars: letters, digits, `_`, `-`, `/`.
- **Inline vs frontmatter**: inline `#tag` works anywhere in the body; frontmatter `tags:` is preferred for structured classification.

Before creating a new tag, always run `list` first and reuse an existing one if a close match exists.

## Backlinks / Link Maintenance

Backlinks are `[[Note Name]]` references pointing TO a note. Obsidian builds them automatically in-app; on the filesystem you maintain them by editing the source notes.

- **Find backlinks to a note**: `search_files` with `target: "content"`, `pattern: "\\[\\[Note Name"` and `file_glob: "*.md"` across the vault. The same prefix matches both `[[Note Name]]` and `[[Note Name|...]]`.
- **Rename a note safely**:
  1. Move the file with `terminal` (`mv "old.md" "new.md"`), or read+write+delete via file tools.
  2. Search for `[[Old Name]]` and `[[Old Name|...]]` across the vault.
  3. Patch each referring note to use `[[New Name]]` (preserve display text after `|`).
- **Delete a note safely**: search for backlinks first; either remove the links or convert them to plain text, then delete the file.

## Daily Notes

If the user keeps a daily-notes folder (commonly `Daily/`, `日记/`, or `journals/`), create today's note with `write_file` at the conventional path. Use `YYYY-MM-DD.md` naming unless the user has an existing convention. If unsure, list the vault root first to discover the folder.

## Canvas Files

`.canvas` files are JSON describing nodes (text/file/link/group) and edges on a 2D plane. See `references/canvas.md` for the spec. Edit with `write_file` producing valid JSON; do not hand-edit fragments. Coordinates: `x` increases right, `y` increases down; position is the top-left corner.

## Obsidian CLI (optional enhancement)

If `obsidian-cli` is installed (check with `terminal` running `which obsidian-cli`), it can automate some operations more safely than raw filesystem edits:

- `obsidian-cli print "note"` — print note content
- `obsidian-cli search "keyword"` — search note titles
- `obsidian-cli search-content "keyword"` — search note content
- `obsidian-cli create "path/note.md" --content "..."` — create note
- `obsidian-cli daily` — open today's daily note
- `obsidian-cli frontmatter "note" --set "key:value"` — write frontmatter field
- `obsidian-cli move "old.md" "new.md"` — rename note (auto-updates backlinks)
- `obsidian-cli list` — list vault files

Prefer the filesystem-first workflows above when `obsidian-cli` is unavailable. Use `obsidian-cli move` for renames when available, since it updates backlinks automatically.

## References

- `references/markdown.md` — Obsidian Flavored Markdown reference (wikilinks, embeds, callouts, frontmatter).
- `references/canvas.md` — JSON Canvas spec for `.canvas` files.
