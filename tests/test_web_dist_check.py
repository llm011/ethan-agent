"""前端产物（`ethan/web_dist/`）陈旧检测的测试。

## 为什么值得单独测

这个检查的**唯一价值**是准确：误报会让人以后无视这条警告，漏报就回到
「会话详情页白屏但没有任何提示」的老路上（2026-11-16 的真实故障）。

所以这里重点测边界：没构建前端、没有源码树、时间差在容差内、依赖目录变动
不该触发。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ethan.interface.web_dist_check import check_stale_web_dist


def _make_tree(tmp_path: Path, *, dist_ts: float, src_ts: float) -> tuple[Path, Path]:
    """造一对 web_dist / web 目录，分别设定 mtime。"""
    web_dist = tmp_path / "ethan" / "web_dist"
    web_src = tmp_path / "web"
    web_dist.mkdir(parents=True)
    web_src.mkdir(parents=True)

    index = web_dist / "index.html"
    index.write_text("<html></html>")
    os.utime(index, (dist_ts, dist_ts))

    src = web_src / "app.tsx"
    src.write_text("export default 1")
    os.utime(src, (src_ts, src_ts))
    return web_dist, web_src


def test_no_warning_when_dist_is_fresh(tmp_path):
    now = time.time()
    web_dist, src = _make_tree(tmp_path, dist_ts=now, src_ts=now - 3600)
    assert check_stale_web_dist(web_dist, src) is None


def test_warns_when_src_newer_than_dist(tmp_path):
    now = time.time()
    web_dist, src = _make_tree(tmp_path, dist_ts=now - 7 * 86400, src_ts=now)
    msg = check_stale_web_dist(web_dist, src)
    assert msg, "源码比产物新时必须报警"
    assert "web_dist" in msg
    assert "build:web" in msg, "警告里要带可执行的修复命令"


def test_tolerance_absorbs_near_simultaneous_timestamps(tmp_path):
    """build 与 checkout 的时间戳常常贴近，容差内不该误报。"""
    now = time.time()
    web_dist, src = _make_tree(tmp_path, dist_ts=now, src_ts=now + 30)
    assert check_stale_web_dist(web_dist, src) is None


def test_no_dist_means_no_warning(tmp_path):
    """没构建过前端是合法状态（纯 API 部署），不该报警。"""
    web_dist = tmp_path / "ethan" / "web_dist"
    web_dist.mkdir(parents=True)
    web_src = tmp_path / "web"
    web_src.mkdir()
    assert check_stale_web_dist(web_dist, web_src) is None


def test_no_source_tree_means_no_warning(tmp_path):
    """wheel 安装没有 `web/` 源码树，无从比较 —— 静默跳过。"""
    now = time.time()
    web_dist, _src = _make_tree(tmp_path, dist_ts=now - 86400, src_ts=now)
    assert check_stale_web_dist(web_dist, tmp_path / "nope") is None


def test_node_modules_does_not_trigger(tmp_path):
    """`web/node_modules` 的变动不该造成误报。

    只扫源码扩展名、且不递归进依赖目录——否则装个包就报「产物陈旧」。
    """
    now = time.time()
    web_dist, src = _make_tree(tmp_path, dist_ts=now, src_ts=now - 3600)
    stale_dep = src / "node_modules" / "pkg" / "index.d.ts"
    stale_dep.parent.mkdir(parents=True)
    stale_dep.write_text("// dts")
    os.utime(stale_dep, (now + 600, now + 600))
    # .d.ts 不在扫描扩展名里；即便扫到，也只应报源码而非依赖
    msg = check_stale_web_dist(web_dist, src)
    assert msg is None, f"依赖目录变动不应误报：{msg}"


def test_check_never_raises_on_weird_input(tmp_path):
    """自检跑在服务启动路径上，任何异常都必须被吞掉。"""
    assert check_stale_web_dist(tmp_path / "a" / "b", tmp_path / "c") is None
