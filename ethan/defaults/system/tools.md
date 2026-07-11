# 工具提示与个人建议

## 工具选择优先级

- 天气查询 → 优先用 `get_weather`（专用 API，稳定快速），web_search 作为兜底
- 定时提醒、周期任务、定时执行 → 优先用 `schedule_create`，不要写脚本或用 cron 命令行
- 搜索文件内容 → 用 `rg_search`，不要用 `shell grep`
- 查找文件位置 → 用 `fd_find`，不要用 `shell find`
- 存储/检索用户知识 → 用 `knowledge_add` / `knowledge_search`

# 在此记录常用工具的调用方式、个人偏好的软件推荐，或你发现值得复用的 shell 命令封装。
# 示例：
#   - 调用某个本地 API 的 curl 命令
#   - 控制智能家居设备的命令
#   - 个人偏好的软件推荐
