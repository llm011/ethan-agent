# 批量获取热门划线（>20 条）的可靠做法

`/book/bestbookmarks` 单次只返回 **top 20** 条热门划线（按热度排序）。要拿到更多（比如 80 条），必须**按章节逐个拉取再合并**。

## 步骤

1. 先调 `/book/chapterinfo` 拿章节列表，提取每个 `chapterUid`
   - 注意：返回结构是顶层 `chapters` 数组，不是 `data`
   - 字段：`chapterUid`、`level`（1=主章节，2=子节）、`title`
2. 对每个 `chapterUid` 调一次 `/book/bestbookmarks`（`chapterUid` 传具体值，不传 0）
3. 合并所有返回的 `items`，按 `markText` 去重（同一段话可能跨章节重复出现）
4. 按 `totalCount`（划线人数）降序排序
5. 截取前 N 条即为全书的 Top N 热门划线

## 频率限制避坑（关键！）

- **报错很迷惑**：限流时返回 `{"errcode": -2010, "errmsg": "用户不存在"}`，**不是 key 失效**，而是调用太频繁被限
- 共享体验 key（`wrk-CjwxNd85TU0QHbCT9cRXNwAA`）限制较严，批量拉取极易触发
- **间隔**：每条请求之间至少 sleep 1~2 秒
- **重试策略**：遇到 `errcode:-2010` 时指数退避（5s → 10s → 20s → 40s → 60s 封顶，最多 5 次），不要立即重试；等待期间每 10s 用 `chapterUid=0` 轻量请求探测是否解封，解封立即恢复，避免死等
- 建议整体脚本跑在 300s+ 超时的 shell 里，52 章约需 2-4 分钟
- 若连续多次限流，可以先只拉 `chapterUid=0`（全书 top20）兜底，等限流窗口过了再补全量

## 参考脚本

见本技能 `scripts/fetch_bestbookmarks.py`（如存在）；否则按上述步骤用 curl + python 循环即可。
