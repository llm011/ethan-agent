# 工具提示与个人建议

## 工具选择优先级

- 天气查询 → 优先用 `get_weather`（专用 API，稳定快速），web_search 作为兜底
- 定时提醒、周期任务、定时执行 → 优先用 `schedule_create`，不要写脚本或用 cron 命令行
- 搜索文件内容 → 用 `rg_search`，不要用 `shell grep`
- 查找文件位置 → 用 `fd_find`，不要用 `shell find`
- 存储/检索用户知识 → 用 `knowledge_add` / `knowledge_search`（见下方「记录/笔记入口路由」）
- 读取图片文件 → 用 `file_read`，图片会自动在前端渲染为可放大查看的图片卡片，无需在回复正文中重复贴出图片内容；你只需描述分析结论

## 记录/笔记入口路由（重要——别在多个笔记出口间瞎猜）

系统里有多个"能记东西"的地方，**默认落点永远是内置 `knowledge_*` 工具**。只有命中明确特征时才走专用出口：

| 要记的东西 | 走哪里 | 说明 |
|---|---|---|
| 用户自己的想法/事实/资料/纪要/PRD/设计 | **内置 `knowledge_*`**（默认） | scene 区分 work/life；这是系统知识库基建 |
| 聊到的人（朋友/同事/家人） | **people-kb**（底层仍是 `knowledge_*`） | 一人一档 `人物 - {名字}` |
| 项目进展/业务范围/文档收藏/工作沉淀 | **work-notes**（底层仍是 `knowledge_*`） | 结构化条目 |
| 小灵感/闪念/碎片（用户点名 flomo 或语境是"记个灵感"） | **flomo** | 短笔记专用；用得少 |
| 收藏外部文章/视频/链接、查已收藏内容 | **getnote** | 手机剪藏入口，外部输入沉淀 |
| 消息里带 URL（任何链接） | **先走 url-process** | 它判断平台再选路径，可能转 getnote/lark-doc/work-notes |
| Obsidian 特有功能（双链/canvas/日记/backlink） | **obsidian** | 普通读写不用它；配了 Obsidian 后端时 `knowledge_*` 会自动落 vault |
| 把多来源编译成互链 wiki（重加工/定时维护） | **llm-wiki** | 通常定时任务调用，非平时随手记 |

**关键**：
- "记一下/存一下"这类泛化词 **默认走 `knowledge_*`**，不要默认跳到 flomo/getnote/obsidian。
- `obsidian` 只是知识库的一种**后端实现**——用户把后端配成 Obsidian 时，`knowledge_*` 自动落到 vault，此时**不需要**加载 obsidian 技能；它只在用到 vault 特有功能时才上。
- 用户默认不配置 Obsidian，此时 `knowledge_*` 走系统知识库基建（本地多层级 markdown 目录，按 `tags[0]` 分子目录）。

## 知识库写入硬约束

涉及写入知识库/笔记/资料/纪要/PRD/设计文档等条目时，**必须**遵守：

- ✅ 写入 → `knowledge_add(title, content, tags, scene, frontmatter)`
- ✅ 追加/替换 → `knowledge_edit(source, content, mode="append"|"replace", scene, frontmatter)`
- ✅ 读取 → `knowledge_search` 或 `knowledge_read`
- ❌ 禁止 `file_write` 直写 `.md` 文件
- ❌ 禁止 `shell` 的 `mkdir` / `cat` / `echo` / `python3 -c "open(...).write(...)"` 拼接路径写文件
- ❌ 禁止自己拼接 vault 路径——`scene` 参数决定子目录，由后端自动管理

**必传参数**：
- `scene`：`work` / `life`，不传会平铺到 vault 根目录（禁止）
- `frontmatter={"source": "原始URL"}`：内容来自外部链接时必传
- `tags`：层级标签如 `["work/coze", "work/prd"]`，`tags[0]` 自动成为 `type` 字段

**为什么**：knowledge_* 工具会自动加 frontmatter（`yaml.safe_dump` 安全生成）、建子目录、建索引支持全文搜索；file_write 直写会绕过这一切，导致路径平铺根目录、frontmatter 字段缺失、搜索查不到、重复写入不 dedup。

**关联技能**：详细规范见 `obsidian` 技能的 SKILL.md。涉及人物/名片记录时 `skill_read people-kb`；团队/绩效/CR 时 `skill_read team-manager`；项目/文档沉淀时 `skill_read work-notes`。

## 批处理意识

同类操作必须合并为单次脚本/循环，不要逐个 `python3 -c` / `shell` 调用：
- ✅ 一次 `python3 -c` 处理 5 个文件 → `for f in files: process(f)`
- ❌ 5 个独立的 `python3 -c` 命令处理 5 个同构文件
- ✅ 一次 `knowledge_add` 调用写入一篇笔记
- ❌ 写脚本生成再 `file_write` 落盘

# 在此记录常用工具的调用方式、个人偏好的软件推荐，或你发现值得复用的 shell 命令封装。
# 示例：
#   - 调用某个本地 API 的 curl 命令
#   - 控制智能家居设备的命令
#   - 个人偏好的软件推荐
