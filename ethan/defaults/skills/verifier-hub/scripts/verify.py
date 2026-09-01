#!/usr/bin/env python3
"""output-verifier: 产物交付前的确定性校验 CLI（verifier-hub 简化版）。

回答「文件在不在、空不空、有没有占位符、语法对不对」这类有确定答案的问题，
替代"让模型读一遍再猜"。每次调用在 stdout 输出一个 JSON 对象：

    {"ok": true,  "tool": "check", "result": {"passed": true, ...}, "evidence": {"quote": "..."}}
    {"ok": false, "tool": "check", "error": {"code": "...", "msg": "..."}}

- ok 表示工具本身是否执行成功；校验结论在 result.passed。
- stdlib only，无第三方依赖。

子命令：
    file   <path> [--expect-ext .md] [--allow-empty]     存在/非空/扩展名
    text   <path> [--must-contain K]...                  空白/占位符/关键词审计
    json   <path> [--must-contain-key K]...              JSON 可解析 + 键存在
    code   <path> [--lang py|js]                         语法编译检查
    html   <path>                                        可解析 + 非空 + 占位符
    image  <path>                                        非空 + 魔数校验
    check  <path> --expect-ext .xx [--must-contain K]... 一键全家桶（交付前用这个）
"""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import re
import subprocess
import sys

# ---------------------------------------------------------------- 输出协议

def emit(tool: str, result: dict, quote: str) -> None:
    print(json.dumps(
        {"ok": True, "tool": tool, "result": result,
         "evidence": {"quote": quote}},
        ensure_ascii=False))


def fail(tool: str, code: str, msg: str) -> None:
    print(json.dumps(
        {"ok": False, "tool": tool, "error": {"code": code, "msg": msg}},
        ensure_ascii=False))
    sys.exit(2)


def read_text(path: str, tool: str) -> str:
    if not os.path.isfile(path):
        fail(tool, "FILE_NOT_FOUND", "文件不存在: {}".format(path))
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        fail(tool, "READ_ERROR", "读取失败: {}".format(e))


# ---------------------------------------------------------------- 占位符审计

PLACEHOLDER_PATTERNS = [
    (r"LOREM IPSUM", "lorem ipsum 假文"),
    (r"\bTODO\b", "TODO 待办"),
    (r"\bFIXME\b", "FIXME 待修"),
    (r"XXX", "XXX 占位"),
    (r"占位", "「占位」"),
    (r"待补充", "「待补充」"),
    (r"待填写", "「待填写」"),
    (r"待定", "「待定」"),
    (r"此处省略", "「此处省略」"),
    (r"\{ *[a-z_]*(placeholder|todo|xxx|fill|content) *\}", "{placeholder} 式占位"),
    (r"<[a-z_ ]*(placeholder|todo|your[_ ]|insert)[^>]*>", "<placeholder> 式占位"),
    (r"\[\s*插入[^\]]{0,12}\]", "[插入…] 式占位"),
    (r"\?{3,}", "??? 占位"),
    (r"TBD\b", "TBD 待定"),
]
PLACEHOLDER_RE = re.compile("|".join("(?:{})".format(p) for p, _ in PLACEHOLDER_PATTERNS), re.IGNORECASE)


def placeholder_hits(text: str) -> list:
    hits = []
    for pat, label in PLACEHOLDER_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            start = max(0, m.start() - 10)
            ctx = text[start:m.end() + 10].replace("\n", " ")
            hits.append({"kind": label, "match": m.group(0)[:40], "context": ctx})
    return hits


# ---------------------------------------------------------------- 子命令

def cmd_file(args) -> None:
    tool = "file"
    p = args.path
    if not os.path.exists(p):
        fail(tool, "FILE_NOT_FOUND", "不存在: {}".format(p))
    if not os.path.isfile(p):
        fail(tool, "NOT_A_FILE", "不是普通文件: {}".format(p))
    size = os.path.getsize(p)
    ext = os.path.splitext(p)[1].lower()
    problems = []
    if size == 0 and not args.allow_empty:
        problems.append("文件为空（0 字节）")
    if args.expect_ext and ext != args.expect_ext.lower():
        problems.append("扩展名 {} != 预期 {}".format(ext or "(无)", args.expect_ext))
    result = {"passed": not problems, "size_bytes": size, "ext": ext, "problems": problems}
    quote = "{}：{} 字节，扩展名 {}".format(p, size, ext or "(无)")
    if problems:
        quote += "；问题: " + "; ".join(problems)
    emit(tool, result, quote)


def cmd_text(args) -> None:
    tool = "text"
    text = read_text(args.path, tool)
    stripped = text.strip()
    problems, facts = [], {}
    facts["chars"] = len(text)
    facts["non_ws_chars"] = len("".join(text.split()))
    if not stripped:
        problems.append("内容为空白（全是空白字符）")
    hits = placeholder_hits(text)
    facts["placeholders"] = hits
    if hits:
        problems.append("发现 {} 处占位符/异常标记".format(len(hits)))
    missing = [k for k in args.must_contain or [] if k not in text]
    facts["missing_keywords"] = missing
    if missing:
        problems.append("缺少关键词: {}".format(", ".join(missing)))
    result = {"passed": not problems, **facts, "problems": problems}
    quote = "{}：{} 字符（非空白 {}）".format(args.path, facts["chars"], facts["non_ws_chars"])
    if hits:
        quote += "，占位符 {} 处（如「{}」）".format(len(hits), hits[0]["match"])
    if not problems:
        quote += "，无占位符，关键词齐全"
    else:
        quote += "；问题: " + "; ".join(problems)
    emit(tool, result, quote)


def cmd_json(args) -> None:
    tool = "json"
    text = read_text(args.path, tool)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        fail(tool, "PARSE_ERROR", "JSON 解析失败: {} (line {})".format(e.msg, e.lineno))
    problems = []
    if isinstance(data, dict):
        keys = list(data.keys())
        missing = [k for k in args.must_contain_key or [] if k not in data]
        if missing:
            problems.append("缺少键: {}".format(", ".join(missing)))
    else:
        keys = None
        if args.must_contain_key:
            problems.append("顶层不是对象，无法检查键")
    if not str(data).strip():
        problems.append("解析结果为空值")
    result = {"passed": not problems, "top_type": type(data).__name__,
              "keys": keys, "problems": problems}
    quote = "{}：JSON 合法，顶层 {}，{} 个键".format(
        args.path, type(data).__name__, len(keys) if keys else "-")
    if problems:
        quote += "；问题: " + "; ".join(problems)
    emit(tool, result, quote)


def cmd_code(args) -> None:
    tool = "code"
    p = args.path
    if not os.path.isfile(p):
        fail(tool, "FILE_NOT_FOUND", "不存在: {}".format(p))
    lang = args.lang or ({"py": "py", "js": "js", "mjs": "js"}.get(os.path.splitext(p)[1].lstrip(".").lower()))
    if lang == "py":
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            try:
                py_compile.compile(p, doraise=True, cfile=os.path.join(td, "c.pyc"))
            except py_compile.PyCompileError as e:
                fail(tool, "SYNTAX_ERROR", "Python 语法错误: {}".format(e.msg.splitlines()[0] if e.msg else e))
        emit(tool, {"passed": True, "lang": "py"}, "{}：Python 编译通过".format(p))
    elif lang == "js":
        node = _which("node")
        if not node:
            fail(tool, "DEP_MISSING", "需要 node 做语法检查，环境中未找到")
        r = subprocess.run([node, "--check", p], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            err_line = next((x for x in (r.stderr or "").strip().splitlines()
                             if x.strip() and not x.startswith(("Node.js", "    at "))), "未知错误")
            fail(tool, "SYNTAX_ERROR", "JS 语法错误: {}".format(err_line[:200]))
        emit(tool, {"passed": True, "lang": "js"}, "{}：node --check 通过".format(p))
    else:
        fail(tool, "BAD_ARGS", "无法识别语言（用 --lang py|js，或文件用 .py/.js/.mjs 后缀）")


def _which(name: str):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


MAGIC = {"png": b"\x89PNG", "jpg": b"\xff\xd8\xff", "gif": b"GIF8",
         "webp": b"RIFF", "bmp": b"BM", "ico": b"\x00\x00\x01\x00"}


def cmd_image(args) -> None:
    tool = "image"
    p = args.path
    if not os.path.isfile(p):
        fail(tool, "FILE_NOT_FOUND", "不存在: {}".format(p))
    size = os.path.getsize(p)
    with open(p, "rb") as f:
        head = f.read(12)
    kind = None
    for name, magic in MAGIC.items():
        if head.startswith(magic):
            kind = name
            if name == "webp" and head[8:12] != b"WEBP":
                kind = None
            break
    problems = []
    if size == 0:
        problems.append("文件为空（0 字节）")
    elif kind is None:
        problems.append("魔数不匹配任何常见图片格式（可能损坏或非图片）")
    result = {"passed": not problems, "size_bytes": size, "detected": kind, "problems": problems}
    quote = "{}：{} 字节，识别为 {}".format(p, size, kind or "未知格式")
    if problems:
        quote += "；问题: " + "; ".join(problems)
    emit(tool, result, quote)


def cmd_html(args) -> None:
    from html.parser import HTMLParser

    class Probe(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = 0
            self.text_chars = 0
            self.in_body = False

        def handle_starttag(self, tag, attrs):
            self.tags += 1
            if tag == "body":
                self.in_body = True

        def handle_endtag(self, tag):
            if tag == "body":
                self.in_body = False

        def handle_data(self, data):
            if self.in_body:
                self.text_chars += len(data.strip())

    tool = "html"
    text = read_text(args.path, tool)
    probe = Probe()
    try:
        probe.feed(text)
    except Exception as e:  # noqa: BLE001 — html.parser 对烂 HTML 宽容，但保险起见
        fail(tool, "PARSE_ERROR", "HTML 解析失败: {}".format(e))
    problems = []
    if probe.tags == 0:
        problems.append("没有任何 HTML 标签")
    if probe.text_chars < 10:
        problems.append("正文可见文本过少（{} 字符）".format(probe.text_chars))
    hits = placeholder_hits(text)
    if hits:
        problems.append("发现 {} 处占位符".format(len(hits)))
    result = {"passed": not problems, "tags": probe.tags,
              "body_text_chars": probe.text_chars, "placeholders": hits,
              "problems": problems}
    quote = "{}：{} 个标签，正文 {} 字符".format(args.path, probe.tags, probe.text_chars)
    if problems:
        quote += "；问题: " + "; ".join(problems)
    emit(tool, result, quote)


# ---------------------------------------------------------------- 一键全家桶

TYPE_BY_EXT = {".md": "text", ".txt": "text", ".json": "json", ".html": "html",
               ".htm": "html", ".py": "code", ".js": "code", ".mjs": "code",
               ".png": "image", ".jpg": "image", ".jpeg": "image",
               ".gif": "image", ".webp": "image"}


def cmd_check(args) -> None:
    """file + 类型专属检查 串成一个 verdict。"""
    tool = "check"
    ext = os.path.splitext(args.path)[1].lower()
    expect = args.expect_ext or ext
    steps = []

    def run(name, fn, *a, **kw):
        r = _capture(fn, *a, **kw)
        steps.append({"step": name, **r})
        return r

    def _capture(fn, *a, **kw):
        import contextlib
        import io
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                fn(*a, **kw)
        except SystemExit:
            pass
        try:
            return json.loads(buf.getvalue())
        except json.JSONDecodeError:
            return {"ok": False, "error": {"code": "INTERNAL", "msg": "子检查无输出"}}

    f = run("file", _file_impl, args.path, expect, False)
    t = args.type or TYPE_BY_EXT.get(ext)
    v = None
    if t == "text":
        v = run("text", _text_impl, args.path, args.must_contain or [])
    elif t == "json":
        v = run("json", _json_impl, args.path, args.must_contain or [])
    elif t == "code":
        v = run("code", _code_impl, args.path)
    elif t == "html":
        v = run("html", _html_impl, args.path)
    elif t == "image":
        v = run("image", _image_impl, args.path)
    else:
        steps.append({"step": "content", "ok": True, "skipped": True,
                      "reason": "未知类型 {}，只做了文件级检查".format(ext)})

    def step_failed(s: dict) -> bool:
        # 工具执行失败（ok:false）或校验未通过（passed:false）都算失败；
        # result.passed 不存在且 ok:true 的情况只可能出现在 skipped 步骤，不算失败。
        if s.get("ok") is False or s.get("error"):
            return True
        r = s.get("result") or {}
        return r.get("passed") is False

    all_ok = not step_failed(f)
    if v is not None:
        all_ok = all_ok and not step_failed(v)
    result = {"passed": all_ok, "type": t, "steps": steps}
    bad = [s for s in steps if step_failed(s)]
    if bad:
        msgs = []
        for s in bad:
            if s.get("error"):
                msgs.append("{}: {}".format(s["step"], s["error"]["msg"]))
            else:
                msgs.extend("{}: {}".format(s["step"], p) for p in s["result"]["problems"])
        quote = "{}：未通过 — {}".format(args.path, "; ".join(msgs))
    else:
        quote = "{}：通过（{} 类型，file + {} 检查均无问题）".format(args.path, t or "?", "content" if v else "file")
    emit(tool, result, quote)


# 供 check 调用的底层实现（直接复用子命令主体，绕开 argparse）

def _file_impl(path, expect_ext, allow_empty):
    ns = argparse.Namespace()
    ns.path, ns.expect_ext, ns.allow_empty = path, expect_ext, allow_empty
    cmd_file(ns)


def _text_impl(path, keywords):
    ns = argparse.Namespace()
    ns.path, ns.must_contain = path, keywords
    cmd_text(ns)


def _json_impl(path, keywords):
    ns = argparse.Namespace()
    ns.path, ns.must_contain_key = path, keywords
    cmd_json(ns)


def _code_impl(path):
    ns = argparse.Namespace()
    ns.path, ns.lang = path, None
    cmd_code(ns)


def _html_impl(path):
    ns = argparse.Namespace()
    ns.path = path
    cmd_html(ns)


def _image_impl(path):
    ns = argparse.Namespace()
    ns.path = path
    cmd_image(ns)


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(prog="verify.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("file", help="存在/非空/扩展名")
    s.add_argument("path")
    s.add_argument("--expect-ext", default=None)
    s.add_argument("--allow-empty", action="store_true")
    s.set_defaults(fn=cmd_file)

    s = sub.add_parser("text", help="空白/占位符/关键词")
    s.add_argument("path")
    s.add_argument("--must-contain", action="append")
    s.set_defaults(fn=cmd_text)

    s = sub.add_parser("json", help="JSON 可解析 + 键存在")
    s.add_argument("path")
    s.add_argument("--must-contain-key", action="append")
    s.set_defaults(fn=cmd_json)

    s = sub.add_parser("code", help="语法编译检查")
    s.add_argument("path")
    s.add_argument("--lang", choices=["py", "js"], default=None)
    s.set_defaults(fn=cmd_code)

    s = sub.add_parser("html", help="可解析 + 非空 + 占位符")
    s.add_argument("path")
    s.set_defaults(fn=cmd_html)

    s = sub.add_parser("image", help="非空 + 魔数")
    s.add_argument("path")
    s.set_defaults(fn=cmd_image)

    s = sub.add_parser("check", help="一键全家桶（交付前用这个）")
    s.add_argument("path")
    s.add_argument("--expect-ext", default=None)
    s.add_argument("--type", choices=["text", "json", "html", "code", "image"], default=None)
    s.add_argument("--must-contain", action="append")
    s.set_defaults(fn=cmd_check)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — 兜底包装成协议内错误
        fail("internal", "INTERNAL", "未预期的错误: {}: {}".format(type(e).__name__, e))
