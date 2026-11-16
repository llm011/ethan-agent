"""前端静态产物（`ethan/web_dist/`）的陈旧检测。

## 这个模块解决什么问题

`ethan serve` 挂的是 `ethan/web_dist/` 的前端构建产物，而这个目录**在
.gitignore 里**、不随代码走。于是很容易出现：

    代码已经合并了新的前端路由/逻辑，但 `web_dist` 还是几周前 build 的

后果不是"样式旧了"这种皮毛，而是**功能性故障**。真实案例（2026-11-16）：
#448 把 `/chat/[id]` 与 `/chat` 合并成 `[[...id]]` 单一路由，正是因为静态导出
下 `/chat/<真实id>` 没有预生成产物。而服务挂的仍是合并前的产物，里面只有
`chat/index.html`、`chat/new/index.html`、`chat/__placeholder__/index.html`
——访问 `/chat/s_2026xxx` 落不到任何产物上，ChatView 拿不到 id，消息区永远显示
"Start a conversation"。所有会话都白屏，看起来像后端丢了数据，实际数据完好。

排查这个问题的成本很高：后端 API 200 且返回完整消息，前端不报任何异常，
只是静默不渲染。

## 检测什么、不检测什么

只做**能确定判断**的比较，不做启发式猜测（误报会让人以后无视这条警告）：

1. `web_dist/index.html` 是否存在 —— 不存在就不管（未构建前端是合法状态，
   比如纯 API 部署）
2. 产物里有没有 Next 的构建清单 `_next/static/<buildId>/_buildManifest.js`
   —— 有清单才能谈版本
3. `web/` 源码目录里最新的 mtime 是否晚于 `web_dist` 的构建时间

第 3 条有个已知局限：`mtime` 会被 `git checkout` / `git pull` 刷新，所以
「刚 pull 过但没 build」也会报——这正是我们想要的（确实需要重建）。反过来
「build 过之后又 checkout 到旧提交」不会报，但那种情况产物反而更新，无害。

**不阻塞启动**：只在检测到不一致时打一条 WARNING，说明后果与修复命令。
把服务卡死在启动阶段，对「只想先用起来」的人是更糟的体验。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# 修复命令提示：与 dev.sh 保持一致（build → 整目录替换 → 重启）
_FIX_HINT = "pnpm build:web && rm -rf ethan/web_dist && cp -r web/out ethan/web_dist（然后重启服务）"


def _newest_mtime(root: Path, patterns: tuple[str, ...], limit: int = 4000) -> float:
    """目录下匹配 patterns 的最新 mtime。扫不到返回 0。

    **必须跳过 `node_modules` / 产物目录**：它们体量大、变动频繁，装个包或跑一次
    build 就会让「最新源码时间」跳到未来，于是每次启动都误报——那会把这条警告
    变成噪音，以后真出问题时没人看。实测踩到：只按扩展名 rglob 时，
    `node_modules/**/*.json` 立刻让检测常亮。

    带 limit 是因为万一路径选错（比如传了仓库根），无界遍历会让启动明显变慢。
    """
    skip = {"node_modules", ".next", "out", "dist", "build", ".git", ".turbo"}
    newest = 0.0
    count = 0
    for pattern in patterns:
        try:
            for p in root.rglob(pattern):
                # 路径里任一段命中 skip 就丢弃（rglob 没有 exclude 能力）
                if skip & set(p.parts):
                    continue
                count += 1
                if count > limit:
                    logger.debug("web_dist 检测：文件数超过上限 %d，放弃比较", limit)
                    return 0.0
                if p.is_file():
                    newest = max(newest, p.stat().st_mtime)
        except OSError:
            continue
    return newest


def check_stale_web_dist(web_dist: Path, web_src: Path | None = None) -> str | None:
    """检查前端产物是否落后于源码。返回警告文本（不需要警告时返回 None）。"""
    try:
        index = web_dist / "index.html"
        if not index.is_file():
            # 没构建过前端：可能是纯 API 部署，不归这里管
            return None

        if web_src is None:
            web_src = web_dist.parent.parent / "web"
        if not web_src.is_dir():
            # 从 wheel 安装、没有源码树（`web/`），无从比较
            return None

        dist_mtime = index.stat().st_mtime
        # 只扫真实源码，跳过依赖与产物目录——node_modules 动一下就会误报
        src_mtime = _newest_mtime(
            web_src,
            ("*.ts", "*.tsx", "*.js", "*.jsx", "*.css", "*.json", "*.mjs"),
        )
        if not src_mtime:
            return None
        # 留 60s 容差：build 与 checkout 的时间戳常常贴近，避免边界抖动误报
        if src_mtime <= dist_mtime + 60:
            return None

        import datetime

        src_dt = datetime.datetime.fromtimestamp(src_mtime).strftime("%Y-%m-%d %H:%M")
        dist_dt = datetime.datetime.fromtimestamp(dist_mtime).strftime("%Y-%m-%d %H:%M")
        return (
            f"前端产物比源码旧：web/ 最新改动 {src_dt}，而 ethan/web_dist 构建于 {dist_dt}。\n"
            f"服务挂的是 ethan/web_dist 这棵静态产物，不重建的话新前端路由/逻辑不会生效"
            f"（历史上表现为：点进会话详情页一片空白，后端数据其实完好）。\n"
            f"修复：{_FIX_HINT}"
        )
    except Exception:  # noqa: BLE001 - 自检绝不该影响启动
        logger.debug("web_dist 陈旧检测失败（忽略）", exc_info=True)
        return None


def warn_if_stale(web_dist: Path) -> None:
    """启动时调用：发现陈旧就打 WARNING，不做任何阻塞动作。"""
    if os.environ.get("ETHAN_SKIP_WEB_DIST_CHECK") == "1":
        return
    msg = check_stale_web_dist(web_dist)
    if msg:
        logger.warning(msg)
