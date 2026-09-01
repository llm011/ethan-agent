#!/usr/bin/env python3
"""社区热度扫描：并行拉取 HN / GitHub / arXiv / Reddit，按参与度打分排序。

Usage:
    python3 pulse.py "AI agents"
    python3 pulse.py "RAG" --days 14 --limit 8
    python3 pulse.py "LLM serving" --sources hn,github
    python3 pulse.py "GRPO" --sources arxiv --json
    python3 pulse.py "local llm" --sources reddit --sub LocalLLaMA

数据源（全部免费、无需 API key）:
    hn      Hacker News，Algolia 官方 API，直连可用
    github  GitHub 仓库，走 gh CLI（需 gh auth login）
    arxiv   arXiv 论文，国内网络通常需代理
    reddit  Reddit 帖子，部分网络环境不可达，默认不启用

代理：urllib 自动读取 HTTP_PROXY / HTTPS_PROXY 环境变量，不要在脚本里硬编码：
    export HTTPS_PROXY=http://127.0.0.1:7890

某个源取不到时只降级跳过（写 stderr），不影响其他源，整体不算失败。
"""
import argparse
import concurrent.futures as futures
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

UA = "EthanAgent/1.0"
DEFAULT_SOURCES = "hn,github,arxiv"
ALL_SOURCES = ("hn", "github", "arxiv", "reddit")
PER_SOURCE_TIMEOUT = 20
# 时间衰减指数：越大越偏向"新"，越小越偏向"高参与"。0.6 是偏重热度的折中。
DECAY_EXP = 0.6


class SourceError(Exception):
    """单个数据源不可用（网络、鉴权、命令缺失），由上层降级处理。"""


def _get(url, timeout=PER_SOURCE_TIMEOUT):
    """GET 一个 URL 返回 bytes。代理走环境变量，urllib 默认会读取。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _get_json(url, timeout=PER_SOURCE_TIMEOUT):
    return json.loads(_get(url, timeout).decode("utf-8", "replace"))


def _now():
    return datetime.now(timezone.utc)


def _parse_iso(s):
    """解析 ISO8601 时间戳（兼容 Z 结尾）为 tz-aware datetime。"""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_days(dt, now):
    if dt is None:
        return None
    return max((now - dt).total_seconds() / 86400.0, 0.0)


def _decay(engagement, age_days):
    """参与度按时间衰减：engagement / (age+2)^0.6。缺时间时按 30 天算。"""
    if age_days is None:
        age_days = 30.0
    return round(float(engagement) / ((age_days + 2.0) ** DECAY_EXP), 2)


def _mk(source, title, url, engagement, dt, now, metrics, extra=None, rankable=True):
    """rankable=False 表示该源没有真实热度指标（如 arXiv），不参与跨源混排打分。"""
    age = _age_days(dt, now)
    item = {
        "source": source,
        "title": title,
        "url": url,
        "metrics": metrics,
        "engagement": engagement,
        "rankable": rankable,
        "age_days": round(age, 1) if age is not None else None,
        "score": _decay(engagement, age),
    }
    if extra:
        item.update(extra)
    return item


def fetch_hn(query, days, limit, now, **_):
    since = int(time.time()) - days * 86400
    url = (
        "https://hn.algolia.com/api/v1/search?query="
        + urllib.parse.quote(query)
        + "&tags=story&hitsPerPage="
        + str(max(limit * 3, 20))
        + "&numericFilters=created_at_i>"
        + str(since)
    )
    data = _get_json(url)
    out = []
    for h in data.get("hits", []):
        title = (h.get("title") or "").strip()
        if not title:
            continue
        points = h.get("points") or 0
        comments = h.get("num_comments") or 0
        oid = h.get("objectID")
        created = h.get("created_at")
        out.append(
            _mk(
                "HN",
                title,
                h.get("url") or "https://news.ycombinator.com/item?id=" + str(oid),
                points + 2 * comments,
                _parse_iso(created),
                now,
                {"points": points, "comments": comments},
                {
                    "author": h.get("author"),
                    "discuss_url": "https://news.ycombinator.com/item?id=" + str(oid),
                },
            )
        )
    return out


def fetch_github(query, days, limit, now, new_only=False, **_):
    try:
        proc = subprocess.run(
            [
                "gh", "search", "repos", query,
                "--sort", "updated",
                "--limit", str(max(limit * 3, 20)),
                "--json", "fullName,stargazersCount,createdAt,updatedAt,description,url",
            ],
            capture_output=True,
            text=True,
            timeout=PER_SOURCE_TIMEOUT,
        )
    except FileNotFoundError:
        raise SourceError("gh CLI 未安装（brew install gh）")
    except subprocess.TimeoutExpired:
        raise SourceError("gh search 超时")

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        low = err.lower()
        if "auth" in low or "login" in low:
            raise SourceError("gh 未登录，先跑 gh auth login")
        raise SourceError((err.splitlines()[0] if err else "gh search 失败")[:120])

    out = []
    for r in json.loads(proc.stdout or "[]"):
        stars = r.get("stargazersCount") or 0
        created = _parse_iso(r.get("createdAt"))
        updated = _parse_iso(r.get("updatedAt"))
        # 用 updatedAt 衡量活跃度：仓库 stars 是累积量，最近没动就不算"近期热度"
        if _age_days(updated, now) is not None and _age_days(updated, now) > days:
            continue
        if new_only and _age_days(created, now) is not None and _age_days(created, now) > days:
            continue
        desc = (r.get("description") or "").strip()
        out.append(
            _mk(
                "GitHub",
                r.get("fullName") or "(unknown)",
                r.get("url") or "",
                stars,
                updated,
                now,
                {"stars": stars},
                {
                    "summary": desc[:200],
                    "created": (r.get("createdAt") or "")[:10],
                    "updated": (r.get("updatedAt") or "")[:10],
                },
            )
        )
    return out


def fetch_arxiv(query, days, limit, now, **_):
    url = (
        "https://export.arxiv.org/api/query?search_query=all:"
        + urllib.parse.quote(query)
        + "&sortBy=submittedDate&sortOrder=descending&max_results="
        + str(max(limit * 3, 20))
    )
    raw = _get(url)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise SourceError("arXiv 返回非预期内容：" + str(e))

    out = []
    for entry in root.findall("a:entry", ns):
        title_el = entry.find("a:title", ns)
        title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""
        if not title:
            continue
        published_el = entry.find("a:published", ns)
        dt = _parse_iso(published_el.text if published_el is not None else None)
        age = _age_days(dt, now)
        if age is not None and age > days:
            continue
        id_el = entry.find("a:id", ns)
        abs_url = (id_el.text or "").strip() if id_el is not None else ""
        summary_el = entry.find("a:summary", ns)
        summary = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else ""
        authors = [
            (a.find("a:name", ns).text or "").strip()
            for a in entry.findall("a:author", ns)
            if a.find("a:name", ns) is not None
        ]
        out.append(
            _mk(
                "arXiv",
                title,
                abs_url,
                10.0,
                dt,
                now,
                {"authors": authors[:4]},
                {
                    "summary": summary[:200],
                    "published": (published_el.text or "")[:10] if published_el is not None else "",
                },
                # 论文没有点赞/星标，组内靠提交时间排序即可，不参与跨源混排
                rankable=False,
            )
        )
    return out


def fetch_reddit(query, days, limit, now, sub=None, **_):
    window = "week" if days <= 7 else "month"
    if sub:
        url = (
            "https://www.reddit.com/r/"
            + urllib.parse.quote(sub)
            + "/top.json?t="
            + window
            + "&limit="
            + str(max(limit, 10))
        )
    else:
        url = (
            "https://www.reddit.com/search.json?q="
            + urllib.parse.quote(query)
            + "&sort=top&t="
            + window
            + "&limit="
            + str(max(limit, 10))
        )
    data = _get_json(url)
    out = []
    for c in (data.get("data") or {}).get("children", []):
        d = c.get("data") or {}
        title = (d.get("title") or "").strip()
        if not title:
            continue
        score = d.get("score") or 0
        comments = d.get("num_comments") or 0
        created = d.get("created_utc")
        dt = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
        # 窗口只是粗粒度映射（≤7 天 week、否则 month），返回结果再按 --days 精确筛一遍，
        # 避免把超出时间窗口的 top 帖混进来，和其它源行为对齐。
        age = _age_days(dt, now)
        if age is not None and age > days:
            continue
        out.append(
            _mk(
                "Reddit",
                title,
                "https://www.reddit.com" + (d.get("permalink") or ""),
                score + 2 * comments,
                dt,
                now,
                {"score": score, "comments": comments},
                {"subreddit": d.get("subreddit")},
            )
        )
    return out


FETCHERS = {
    "hn": fetch_hn,
    "github": fetch_github,
    "arxiv": fetch_arxiv,
    "reddit": fetch_reddit,
}


def collect(query, days, limit, sources, sub=None, new_only=False):
    """并发拉取各源。返回 (items, status)；status 记录每源的成功条数或失败原因。"""
    now = _now()
    items = []
    status = {}
    with futures.ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futs = {
            pool.submit(FETCHERS[s], query, days, limit, now, sub=sub, new_only=new_only): s
            for s in sources
        }
        for fut in futures.as_completed(futs):
            s = futs[fut]
            try:
                got = fut.result()
            except SourceError as e:
                status[s] = ("skip", str(e))
            except Exception as e:  # noqa: BLE001 - 单源异常不能拖垮整体
                status[s] = ("skip", "{}: {}".format(type(e).__name__, str(e)[:100]))
            else:
                items.extend(got)
                status[s] = ("ok", len(got))

    items.sort(key=lambda x: x.get("score") or 0, reverse=True)
    return items, status


# item["source"] 存的是显示名（HN/GitHub/arXiv/Reddit），与 ALL_SOURCES 的小写 key 不同，
# 分组遍历要用显示名顺序，否则匹配不上（status 那边才用小写 key）。
SOURCE_ORDER = ("HN", "GitHub", "arXiv", "Reddit")

GROUP_LABEL = {
    "HN": "Hacker News",
    "GitHub": "GitHub 仓库（stars 是累积量，用 created / updated 判断新近度）",
    "arXiv": "arXiv 论文（按提交时间倒序，无热度指标）",
    "Reddit": "Reddit 帖子",
}


def _meta_line(it):
    m = it.get("metrics") or {}
    bits = []
    if "points" in m:
        bits.append("{} 分".format(m["points"]))
    if "score" in m and "points" not in m:
        bits.append("{} 分".format(m["score"]))
    if "stars" in m:
        bits.append("{} stars".format(m["stars"]))
    if "comments" in m:
        bits.append("{} 评论".format(m["comments"]))
    if it.get("published"):
        bits.append(it["published"])
    elif it.get("age_days") is not None:
        bits.append("{} 天前".format(it["age_days"]))
    if it.get("created"):
        bits.append("创建 {}".format(it["created"]))
    if it.get("updated"):
        bits.append("更新 {}".format(it["updated"]))
    if it.get("subreddit"):
        bits.append("r/{}".format(it["subreddit"]))
    return " · ".join(bits)


def _render_one(i, it):
    lines = ["{}. {}".format(i, it["title"])]
    meta = _meta_line(it)
    if meta:
        lines.append("   " + meta)
    if it.get("summary"):
        lines.append("   " + it["summary"])
    if it.get("url"):
        lines.append("   " + it["url"])
    return lines


def render(items, status, query, days, limit, mix=False):
    lines = []
    lines.append("## 社区热度：{}（近 {} 天）".format(query, days))
    lines.append("")
    parts = []
    for s in ALL_SOURCES:
        if s not in status:
            continue
        kind, val = status[s]
        parts.append("{} [ok] {} 条".format(s, val) if kind == "ok" else "{} [skip] {}".format(s, val))
    lines.append("数据源：" + " · ".join(parts))
    lines.append("")

    if not items:
        lines.append("没有取到任何条目。可以换关键词、放宽 --days，或检查网络/代理。")
        return "\n".join(lines)

    if mix:
        # 跨源混排：先在各源内归一化到 0-100，再做时间衰减，避免量纲碾压。
        # 没有真实热度指标的源（arXiv）不参与打分，混排后单独归一组追加到末尾。
        pool = [it for it in items if it.get("rankable", True)]
        unrankable = [it for it in items if not it.get("rankable", True)]
        skipped = sorted({it["source"] for it in unrankable})
        peak = {}
        for it in pool:
            src = it["source"]
            peak[src] = max(peak.get(src, 0.0), float(it.get("engagement") or 0.0))
        for it in pool:
            p = peak.get(it["source"]) or 1.0
            it["norm"] = _decay((float(it.get("engagement") or 0.0) / p) * 100.0, it.get("age_days"))
        pool.sort(key=lambda x: x.get("norm") or 0, reverse=True)
        items = pool
        note = "跨源混排（各源内归一化后按热度+时间衰减排序，共 {} 条，展示前 {} 条）".format(len(items), min(limit, len(items)))
        if skipped:
            note += "；{} 无热度指标，不参与混排，单独附在末尾".format("/".join(skipped))
        lines.append(note)
        lines.append("")
        for i, it in enumerate(items[:limit], 1):
            blk = _render_one(i, it)
            blk[0] = "{}. [{}] {}".format(i, it["source"], it["title"])
            lines.extend(blk)
            lines.append("")
        # 非 rankable 源（如 arXiv）按源分组追加，避免在 mix 下被整体丢弃
        for s in SOURCE_ORDER:
            group = [it for it in unrankable if it["source"] == s]
            if not group:
                continue
            lines.append("### {}（{}）".format(GROUP_LABEL.get(s, s), len(group)))
            lines.append("")
            for i, it in enumerate(group[:limit], 1):
                lines.extend(_render_one(i, it))
                lines.append("")
        return "\n".join(lines)

    lines.append("共 {} 条。各源量纲不同（HN 几百 vs GitHub 十几万），**按源分组**展示，组内各自排序：".format(len(items)))
    lines.append("")
    for s in SOURCE_ORDER:
        group = [it for it in items if it["source"] == s]
        if not group:
            continue
        lines.append("### {}（{}）".format(GROUP_LABEL.get(s, s), len(group)))
        lines.append("")
        for i, it in enumerate(group[:limit], 1):
            lines.extend(_render_one(i, it))
            lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="社区热度扫描（HN / GitHub / arXiv / Reddit）")
    ap.add_argument("query", help="主题词")
    ap.add_argument("--days", type=int, default=30, help="时间窗口天数（默认 30）")
    ap.add_argument("--limit", type=int, default=15, help="最终展示条数（默认 15）")
    ap.add_argument("--sources", default=DEFAULT_SOURCES, help="逗号分隔，可选：" + ",".join(ALL_SOURCES))
    ap.add_argument("--sub", default=None, help="Reddit 子版块（配合 --sources reddit）")
    ap.add_argument("--new", action="store_true", help="GitHub 只保留窗口内新建的仓库")
    ap.add_argument("--mix", action="store_true", help="跨源混排（各源内归一化后排序），默认按源分组")
    ap.add_argument("--json", action="store_true", help="输出结构化 JSON")
    args = ap.parse_args()

    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in FETCHERS]
    if unknown:
        print("未知数据源：{}（可选：{}）".format(",".join(unknown), ",".join(ALL_SOURCES)), file=sys.stderr)
        return 2
    if not sources:
        print("没有指定数据源", file=sys.stderr)
        return 2

    items, status = collect(args.query, args.days, args.limit, sources, sub=args.sub, new_only=args.new)

    for s in ALL_SOURCES:
        if s in status and status[s][0] == "skip":
            print("[warn] {} 跳过：{}".format(s, status[s][1]), file=sys.stderr)

    if args.json:
        print(json.dumps({"query": args.query, "days": args.days, "sources": status,
                          "count": len(items), "items": items}, ensure_ascii=False, indent=2))
    else:
        print(render(items, status, args.query, args.days, args.limit, mix=args.mix))
    return 0


if __name__ == "__main__":
    sys.exit(main())
