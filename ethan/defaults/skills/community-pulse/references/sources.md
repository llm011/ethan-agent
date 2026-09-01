# 数据源细节与故障排查

`scripts/pulse.py` 的四个源都走免费公开 API，不需要 key。这里记录每个源的接口细节、
字段含义和常见故障，排查问题时再读这个文件。

## 打分公式

```
engagement = 真实参与度
score      = engagement / (age_days + 2) ** 0.6
```

- 指数 `0.6` 偏重"热度"而非"新"；调大（如 1.5）会强烈偏向新内容。
- `+2` 是平滑项，避免当天内容除以 0 导致分数爆炸。
- 缺时间字段的条目按 30 天算。

各源 engagement 定义：

| 源 | engagement |
|----|-----------|
| HN | `points + 2 * comments` |
| Reddit | `score + 2 * num_comments` |
| GitHub | `stargazersCount` |
| arXiv | 固定 10.0（无热度指标，组内靠时间排序，`rankable=False`） |

评论权重取 2 倍：一条引发 100 条讨论的帖子，比一个 100 分但无人讨论的帖子信号更强。

## Hacker News

走 Algolia 官方搜索 API：

```
https://hn.algolia.com/api/v1/search?query=<q>&tags=story&hitsPerPage=<n>&numericFilters=created_at_i><ts>
```

- `tags=story` 只取帖子，不要评论。改用 `comment` 可取评论。
- `numericFilters=created_at_i>TS` 在服务端做时间过滤，比拉回来再筛省流量。
- 用 `search`（按相关度+热度）；想要纯时间序可换 `search_by_date`。
- 每条同时给出原文 `url` 和 HN 讨论页 `discuss_url`（`news.ycombinator.com/item?id=<objectID>`）——社区讨论往往比原文更有信息量。

故障：返回空但 HTTP 200 → 关键词太窄，放宽 `--days` 或换词。

## GitHub

走 `gh` CLI（不直接调 REST API，省去鉴权处理）：

```bash
gh search repos "<query>" --sort updated --limit <n> \
  --json fullName,stargazersCount,createdAt,updatedAt,description,url
```

- 需 `gh auth login`，未登录会报 `gh 未登录，先跑 gh auth login`。
- **stars 是累积量**，这是本源最大的解读陷阱。老仓库天然 stars 高，
  所以脚本按 `updatedAt` 排序取「近期有动静」的仓库，再叠加 `updatedAt` 过滤窗口（最近还在更新 = 还活着），
  并输出 `created` / `updated` 供判断。
- 打分的时间衰减也基于 `updatedAt`（不是 `createdAt`），与过滤语义一致：目标是「最近在动的仓库」而非「创建时间新的仓库」。
- `--new` 可只看窗口内**新建**的仓库（用 `createdAt` 再过滤一层）。
- 想看近期 star 增速：免费 API 拿不到，别想办法绕——直接看 `created` 判断。

故障：`gh: command not found` → `brew install gh`；`gh search 超时` → 网络问题，可单独重跑本源。

## arXiv

走官方 Atom API：

```
https://export.arxiv.org/api/query?search_query=all:<q>&sortBy=submittedDate&sortOrder=descending&max_results=<n>
```

- 返回 Atom XML，用 `xml.etree.ElementTree` 解析，命名空间 `http://www.w3.org/2005/Atom`。
- 只有 `submittedDate` 排序，没有热度字段，所以组内按时间倒序。
- `max_results` 拉 3 倍再按 `--days` 客户端过滤（API 不支持时间过滤参数）。
- **国内网络通常需代理**，直连容易超时。

精确检索（按作者、分类、ID）应该用 `arxiv` 技能，本技能只负责"最近有什么新论文"。

## Reddit

```
https://www.reddit.com/r/<sub>/top.json?t=<week|month>&limit=<n>
https://www.reddit.com/search.json?q=<q>&sort=top&t=<week|month>&limit=<n>
```

- 需带 User-Agent（脚本统一用 `EthanAgent/1.0`），否则可能被 429。
- `t=` 窗口只有 hour/day/week/month/year/all 几档，按 `--days` 映射：≤7 天用 week，否则 month。
- 因为 `t=` 只是粗粒度映射，返回结果会再按 `--days` 精确筛一遍（跳过 `age_days > days` 的帖子），避免超窗帖子混进来。
- **国内网络经常不可达**（SSL 握手超时），属预期行为。脚本会降级跳过并打印 `[warn]`，不算失败。
- 不带 `--sub` 时走全站搜索，噪音较大；能确定子版块就尽量用 `--sub LocalLLaMA` 这类精确指定。

## 并发与降级

四个源用 `ThreadPoolExecutor` 并发拉取，单源超时 20 秒。任一源抛异常都被捕获，
转成 `status[src] = ("skip", 原因)`，stdout 照常输出其他源的结果，stderr 打印：

```
[warn] reddit 跳过：URLError: <urlopen error _ssl.c:993: The handshake operation timed out>
```

因此**退出码为 0 不代表所有源都成功**，要看输出头部的 `数据源：` 一行有没有 `[skip]`。

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 正常（可能含部分源降级，看 `[skip]`） |
| 2 | 参数错误（未知数据源、没指定源） |
