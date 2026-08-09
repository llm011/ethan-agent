---
name: wechat-reading
trigger: 微信读书|读书笔记|书架|书城|书籍|阅读统计|阅读时长|书单|推荐书|weread|搜书|找书|热门划线|有声书
description: 微信读书助手 — 搜索书籍、管理书架、查看笔记划线、阅读统计、发现推荐好书。
---

# 微信读书 Skill

通过 Agent API Gateway 调用微信读书接口，支持搜书、书架、笔记、划线、阅读统计、推荐等能力。

## 调用规范

### 统一入口
```
POST https://i.weread.qq.com/api/agent/gateway
```

### 鉴权
- Header：`Authorization: Bearer $WEREAD_API_KEY`
- API Key 绑定用户身份，自动注入，无需手动传用户标识

### 请求格式
所有参数平铺在 body 顶层（不要包在 `params` 里），每次必须带 `skill_version`：

```bash
curl -s -X POST 'https://i.weread.qq.com/api/agent/gateway' \
  -H "Authorization: Bearer $WEREAD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_name":"/store/search","keyword":"三体","scope":10,"skill_version":"1.0.4"}'
```

### 业务参数平铺，不要嵌套
```json
{"api_name":"/user/notebooks","count":100,"skill_version":"1.0.4"}
```
错误：`{"api_name":"...","params":{...}}` 会导致参数未转发、分页失效。

### API Key 配置

密钥存 `~/.ethan/.secrets/wechat-reading.env`，shell 自动注入成 `$WEREAD_API_KEY`。

**首次使用**：如果调用返回 `errcode` 且提示未授权，引导用户：
1. 打开 https://weread.qq.com/r/weread-skills 生成 key
2. Agent 用 `file_write` 写入（不要让用户手动编辑）：
```bash
file_write(path="$HOME/.ethan/.secrets/wechat-reading.env", content='WEREAD_API_KEY="wrk-xxxx"')
chmod 600 ~/.ethan/.secrets/wechat-reading.env
```
3. 重新执行用户请求。写入后 shell 环境变量自动注入，后续 curl 无需手动设 header。

**预置体验 key**（共享，有频率限制）：
```bash
file_write(path="$HOME/.ethan/.secrets/wechat-reading.env", content='WEREAD_API_KEY="wrk-CjwxNd85TU0QHbCT9cRXNwAA"')
chmod 600 ~/.ethan/.secrets/wechat-reading.env
```

---

## 能力索引

| 能力 | api_name | 说明 |
|------|----------|------|
| 搜索书籍 | `/store/search` | 书城搜索，keyword 必填；scope=0(综合)/10(电子书)/14(有声书)/6(作者) |
| 书籍详情 | `/book/info` | bookId 必填；返回书名/作者/评分/简介/出版信息 |
| 章节目录 | `/book/chapterinfo` | bookId 必填；返回章节树含 chapterUid（顶层 `chapters` 数组） |
| 阅读进度 | `/book/getprogress` | bookId 必填；progress 是 0-100 整数(带%号展示)，100=读完 |
| 书架 | `/shelf/sync` | 无参数；返回 books[] + albums[]（专辑/有声书）+ mp(文章收藏入口) |
| 阅读统计 | `/readdata/detail` | mode=weekly/monthly/annually/overall(默认monthly)；totalReadTime 单位秒 |
| 笔记本概览 | `/user/notebooks` | count=20，翻页用 lastSort 游标；总笔记=reviewCount+noteCount+bookmarkCount |
| 划线内容 | `/book/bookmarklist` | bookId 必填；返回划线原文，已过滤书签 |
| 想法点评 | `/review/list/mine` | bookid 必填；返回个人想法/点评内容 |
| 热门划线 | `/book/bestbookmarks` | bookId 必填，chapterUid=0 查全部；**单次只返回 top20** |
| 个性化推荐 | `/book/recommend` | 无参数；返回为你推荐书单 |
| 相似推荐 | `/book/similar` | bookId + count + maxIdx 必填；首次传 count=12 maxIdx=0 |
| 获取所有接口 | `/_list` | 返回全部可用接口及参数定义 |

---

## 快速调用示例

```bash
# 搜书
curl -s -X POST 'https://i.weread.qq.com/api/agent/gateway' \
  -H "Authorization: Bearer $WEREAD_API_KEY" -H "Content-Type: application/json" \
  -d '{"api_name":"/store/search","keyword":"三体","scope":10,"skill_version":"1.0.4"}'

# 书架
curl -s -X POST 'https://i.weread.qq.com/api/agent/gateway' \
  -H "Authorization: Bearer $WEREAD_API_KEY" -H "Content-Type: application/json" \
  -d '{"api_name":"/shelf/sync","skill_version":"1.0.4"}'

# 本月阅读统计
curl -s -X POST 'https://i.weread.qq.com/api/agent/gateway' \
  -H "Authorization: Bearer $WEREAD_API_KEY" -H "Content-Type: application/json" \
  -d '{"api_name":"/readdata/detail","mode":"monthly","skill_version":"1.0.4"}'

# 书籍详情
curl -s -X POST 'https://i.weread.qq.com/api/agent/gateway' \
  -H "Authorization: Bearer $WEREAD_API_KEY" -H "Content-Type: application/json" \
  -d '{"api_name":"/book/info","bookId":"695233","skill_version":"1.0.4"}'

# 书架数量 = books.length + albums.length + (mp非空?1:0)
# 有声书=albums.length，电子书=books.length
# progress 0-100，只有100才表示读完；时长字段都是秒，展示转小时分钟
```

## 关键纪律

- API Key 从 shell 环境变量 `$WEREAD_API_KEY` 获取，别手动写在请求 body 里
- 所有参数平铺在 body 顶层，和 `api_name`/`skill_version` 同级，不要包在 `params` 里
- 书架总数必须 = `books.length + albums.length + (mp非空?1:0)`，专辑/有声书也属于书架
- 用户说书名时先调 `/store/search` 获取 bookId
- 时长字段单位是秒，展示时转为 X小时Y分钟
- 回包有 `deepLink` 时展示为 `[打开阅读]({deepLink})`
- 返回数据量大时只展示摘要，询问用户是否需要详情

## ⚠️ 热门划线批量获取与限流避坑

`/book/bestbookmarks` 单次只返回 **top 20**。要拿更多（如 80 条），必须**按章节拉取再合并**：

1. `/book/chapterinfo` 拿章节列表（结构是顶层 `chapters` 数组，**不是 `data`**），提取每个 `chapterUid`
2. 对每个 `chapterUid` 调 `/book/bestbookmarks`，合并 `items`、按 `markText` 去重、按 `totalCount` 降序排序，截取前 N 条
3. **限流陷阱**：接口被限时返回 `errcode:-2010 "用户不存在"`，**不是 key 失效**！共享体验 key 很容易触发，表现为批量拉取时随机失败
4. **对策**：请求间 sleep 1~2 秒；遇 `-2010` 指数退避（5s→10s→20s→40s→60s 封顶，最多 5 次）重试；等待期间每 10s 用 `chapterUid=0` 轻量请求探测解封，解封立即恢复；脚本放 300s+ 超时；连续失败就先拉 `chapterUid=0` 的 top20 兜底

详细说明见 `references/batch-bookmarks.md`。

activate_tools: shell, file_write


<!-- auto-supplement: 2026-08-09 -->
## 补充要点（自动生成）
新增「热门划线的系统化获取与整理」环节（原有 skill 仅支持 Top 20 一次性返回）。补充：① 划线的跨章节批量拉取策略（按 chapterUid 逐章获取、合并去重、按人数排序），规避微信读书的隐性限流（errcode:-2010 实际为频率限制）；② 限流避坑方案（请求间隔 sleep 1-2s、指数退避重试、延长超时、失败兜底 Top 20）；③ 划线的主题聚类与过滤逻辑（按观点维度分组，避免重复引用）；④ 与 feishu-writer 的连接点：如何将结构化划线进行深度分析（原话 → 观点提炼 → 案例拆解 → 落地启示），而非简单罗列。
