# 工具提示与个人建议

## 工具选择优先级

- 天气查询 → 优先用 `get_weather`（专用 API，稳定快速），web_search 作为兜底
- 定时提醒、周期任务、定时执行 → 优先用 `schedule_create`，不要写脚本或用 cron 命令行
- 搜索文件内容 → 用 `rg_search`，不要用 `shell grep`
- 查找文件位置 → 用 `fd_find`，不要用 `shell find`
- 存储/检索用户知识 → 用 `knowledge_add` / `knowledge_search`

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

**关联技能**：详细规范见 `obsidian` 和 `life-manager` 技能的 SKILL.md。涉及团队/人员/项目记录时优先 `skill_read life-manager`。

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
