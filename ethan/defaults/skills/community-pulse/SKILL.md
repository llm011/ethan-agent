---
name: community-pulse
description: "查技术社区最近在聊什么：并行扫描 Hacker News / GitHub / arXiv / Reddit，按参与度排序出简报。用户问「最近有什么火」「社区在聊什么」「HN 热帖」「技术趋势」「最近动态」时使用。全部免费 API，无需 key。"
version: 1.0.0
author: Ethan Agent
license: MIT
trigger:
  - 社区热度
  - 最近在聊什么
  - 最近有什么火
  - 技术趋势
  - 热度排行
  - HN
  - Hacker News
  - Reddit
  - 最近动态
  - community pulse
platforms: [linux, macos, windows]
metadata:
  ethan:
    tags: [Research, Community, Trending, HackerNews, GitHub, arXiv]
    related_skills: [deep-research, arxiv, rss-briefing, xiaohongshu]
source: internal (hermes agent)
---

# 社区热度（Community Pulse）

一次查询，并行扫多个技术社区，按**用户真实参与度**（点赞、星标、评论）排序出简报。
回答的是"最近大家在聊什么、什么在火"，不是"这个方案该怎么选"。

## 与相邻技能的分工（先判断用哪个）

| 你想知道 | 用哪个 |
|---------|--------|
| 最近社区在聊什么、什么在火 | **本技能** |
| X 和 Y 该选哪个、为什么 | `deep-research`（决策导向，走通用 web + 官方一手来源） |
| 某篇具体论文 / 某作者的论文 | `arxiv`（按关键词、作者、分类精确检索） |
| 我订阅的 RSS / 博客更新了啥 | `rss-briefing` / `blogwatcher` |
| 中文社交平台（小红书）上的内容 | `xiaohongshu` |

> 本技能走**社区信号源**（人的点赞和讨论），`deep-research` 走**权威一手来源**（官方 spec、定价、榜单）。
> 两者互补：先用本技能看风向，再用 deep-research 深挖具体方案。

## 快速开始

```bash
cd ~/.ethan/skills/community-pulse

# 默认扫 HN + GitHub + arXiv，近 30 天
python3 scripts/pulse.py "AI agents"

# 缩短窗口、只看 HN
python3 scripts/pulse.py "RAG" --days 7 --sources hn --limit 10

# 只看最近新建的 GitHub 仓库
python3 scripts/pulse.py "MCP server" --sources github --new

# 跨源混排（各源归一化后竞争，arXiv 不参与）
python3 scripts/pulse.py "AI agents" --mix --limit 10

# 结构化输出，便于自己再加工
python3 scripts/pulse.py "GRPO" --sources arxiv --json
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--days N` | 30 | 时间窗口。GitHub 按 updatedAt 过滤，arXiv 按提交时间过滤 |
| `--limit N` | 15 | **每组**展示条数（分组模式下是每源各 N 条） |
| `--sources a,b` | hn,github,arxiv | 可选 hn / github / arxiv / reddit |
| `--sub NAME` | — | 指定 subreddit（配合 `--sources reddit`） |
| `--new` | 关 | GitHub 只保留窗口内**新建**的仓库 |
| `--mix` | 关 | 跨源混排，默认按源分组 |
| `--json` | 关 | 输出结构化 JSON |

## 数据源

全部免费、无需 API key。

| 源 | 信号 | 可用性 | 备注 |
|----|------|--------|------|
| **hn** | points + comments | 直连可用 | Algolia 官方 API，支持时间窗口过滤 |
| **github** | stars | 需 `gh auth login` | stars 是**累积量**，用 `--new` 或看 created/updated 判断新近度 |
| **arxiv** | 提交时间 | 国内通常需代理 | 论文没有热度指标，只按时间倒序 |
| **reddit** | score + comments | 国内常不可达 | 默认关闭，显式 `--sources reddit` 才启用 |

**某个源取不到时只降级跳过**（stderr 打印 `[warn]`），不影响其他源，整体不算失败。
看到 `[skip]` 就说明那个源这次没取到，换网络或放宽参数再试。

## 输出怎么读

默认**按源分组**展示，因为各源量纲不可比（HN 几百 vs GitHub 十几万 stars，混排会被 GitHub 老仓库刷屏）。
组内各自按"参与度 ÷ 时间衰减"排序——`score = engagement / (age_days + 2)^0.6`，越新越热分越高。

想看跨源统一排名用 `--mix`：各源内先归一化到 0-100 再竞争。arXiv 因无热度指标不参与混排。

## 代理

`urllib` 自动读取 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量，**不要在命令里硬编码代理**：

```bash
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
python3 scripts/pulse.py "GRPO"
```

Docker 容器内访问宿主机代理用 `host.docker.internal`。

## 已知限制

- GitHub 拿不到"近 N 天新增 star 数"（免费 API 限制），只有累积 stars——判断新近度请看 `created` / `updated`。
- Reddit 在国内网络经常不可达，属预期行为，不是脚本 bug。
- 各源并发拉取，单源超时 20 秒。

各源的 API 细节、字段含义与故障排查见 `references/sources.md`。
