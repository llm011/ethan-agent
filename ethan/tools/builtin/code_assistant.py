"""代码助手工具 — 语法校验与受限执行。

两个工具的分工：

· ``code_analyze``：**只读**静态检查，不执行任何代码。做语法解析 + 少量高置信度
  风格提示。不弹授权（无副作用）。
· ``code_run``：需要真的跑代码。**不自己起 subprocess**，而是把代码写成临时文件后
  委托给 ``ShellTool`` 执行，从而自动继承 shell 的全部安全网：高危命令判定与
  consent 授权弹窗、secret 环境注入与 mask、进程组 kill（避免孙进程残留）、
  working_dir 语义。早期版本自己裸调 ``subprocess.run``，既绕过了授权弹窗，
  也在超时时留下孤儿进程。
"""
from __future__ import annotations

import ast
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from ethan.tools.base import BaseTool

# 语言 → (临时文件后缀, 执行器)。执行器为 None 表示当前只做静态检查不执行。
_LANG_SPECS: dict[str, tuple[str, list[str] | None]] = {
    "python": (".py", ["python3"]),
    "py": (".py", ["python3"]),
    "javascript": (".js", ["node"]),
    "js": (".js", ["node"]),
    "typescript": (".ts", ["tsx", "--no-cache"]),
    "ts": (".ts", ["tsx", "--no-cache"]),
    "bash": (".sh", ["bash"]),
    "sh": (".sh", ["bash"]),
}


def _normalize_lang(language: str) -> str:
    return (language or "").strip().lower()


# 代码正文里的「可执行任意副作用」API。shell 的 _DANGEROUS_RE 是给命令行串用的
# 正则（找 `rm -rf ` 这种字面量），识别不了 `subprocess.run(['rm','-rf','/'])`、
# `shutil.rmtree(...)` 这类等价写法——参数被拆成列表元素后不再有 `rm ` 空格。
# 这层按 API 名的扫描补上这个缺口：命中即视为可破坏，走 consent_destructive。
_DANGEROUS_PY_APIS = (
    "os.system",
    "os.popen",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.execv",
    "os.spawn",
    "subprocess.",
    "shutil.rmtree",
    "shutil.move",
    "eval(",
    "exec(",
    "__import__",
    "pty.spawn",
    "ctypes.",
)
# JS/TS：child_process 全系 + 文件删除 + 动态执行
_DANGEROUS_JS_APIS = (
    "child_process",
    "execSync",
    "exec(",
    "spawn(",
    "fork(",
    "fs.rm",
    "fs.rmdir",
    "fs.unlink",
    "eval(",
    "new Function(",
)
_DANGEROUS_SH_APIS = ("rm ", "rmdir", "mkfs", "dd ", "> /dev/sd", "chmod 777")


def _code_risk_markers(code: str, language: str) -> list[str]:
    """返回代码正文里命中的危险 API 列表（只用于判定，不阻断执行）。"""
    lang = _normalize_lang(language)
    if lang in ("python", "py"):
        table = _DANGEROUS_PY_APIS
    elif lang in ("javascript", "js", "typescript", "ts"):
        table = _DANGEROUS_JS_APIS
    elif lang in ("bash", "sh"):
        table = _DANGEROUS_SH_APIS
    else:
        return []
    return [api for api in table if api in code]


class CodeAssistantTool(BaseTool):
    """只读代码静态检查：语法能否通过解析 + 少量高置信度风格提示。"""

    name = "code_analyze"
    description = (
        "静态检查代码：Python 用 AST 解析验证语法，其他语言做基础模式检查。"
        "不会执行代码，无需授权。需要实际跑代码请用 code_run。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要分析的代码"},
            "language": {
                "type": "string",
                "description": "编程语言 (python/js/ts/bash)",
                "default": "python",
            },
        },
        "required": ["code"],
    }
    cacheable = True
    side_effect = False
    no_compress = True

    async def run(self, code: str, language: str = "python") -> str:
        if not code or not code.strip():
            return "代码为空，无可分析内容。"

        lang = _normalize_lang(language)
        issues: list[str] = []
        notes: list[str] = []

        if lang in ("python", "py"):
            issues.extend(_check_python_syntax(code))
            notes.extend(_check_python_style(code))
        elif lang in ("javascript", "js", "typescript", "ts"):
            notes.extend(_check_js_style(code, lang))
        elif lang in ("bash", "sh"):
            issues.extend(_check_bash_syntax(code))
        else:
            notes.append(
                f"暂不支持 {language} 的语言级检查，只做了基础校验。"
                f"支持：{', '.join(sorted(_LANG_SPECS))}"
            )

        lines = ["代码分析报告", "=" * 12, ""]
        if issues:
            lines.append(f"发现 {len(issues)} 个错误：")
            lines.extend(f"  {i}. {msg}" for i, msg in enumerate(issues, 1))
        else:
            lines.append("语法检查：通过")

        if notes:
            lines.append("")
            lines.append(f"提示 {len(notes)} 条：")
            lines.extend(f"  - {msg}" for msg in notes)

        return "\n".join(lines)


def _check_python_syntax(code: str) -> list[str]:
    """用 AST 解析验证语法（比 compile 更能定位问题，且不会真的编译成字节码）。"""
    try:
        ast.parse(code)
    except SyntaxError as e:
        loc = f"第 {e.lineno} 行" if e.lineno else "未知位置"
        return [f"语法错误（{loc}）：{e.msg}"]
    return []


def _check_python_style(code: str) -> list[str]:
    """高置信度提示——只报几乎必然是问题的模式，不做主观风格说教。"""
    notes: list[str] = []
    # 裸 except：会吞掉 KeyboardInterrupt / SystemExit，几乎是 bug 而非风格
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return notes
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            notes.append(f"第 {node.lineno} 行：裸 except 会吞掉 KeyboardInterrupt 等异常，建议指明异常类型")
    # == 比较 None
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(isinstance(op, ast.Eq) for op in node.ops):
            if any(isinstance(c, ast.Constant) and c.value is None for c in node.comparators):
                notes.append(f"第 {node.lineno} 行：与 None 比较建议用 `is None` 而非 `== None`")
    return notes


def _check_js_style(code: str, lang: str) -> list[str]:
    notes: list[str] = []
    if "var " in code:
        notes.append("使用了 `var`，建议改用 const/let（块级作用域）")
    if lang in ("typescript", "ts") and ": any" in code:
        notes.append("使用了 `any`，建议换成具体类型或 unknown")
    return notes


def _check_bash_syntax(code: str) -> list[str]:
    """用 bash -n 只做语法解析（不执行）。"""
    try:
        proc = subprocess.run(
            ["bash", "-n"], input=code, capture_output=True, text=True, timeout=10
        )
        if proc.returncode != 0:
            msg = (proc.stderr or "").strip().splitlines()
            return [f"语法错误：{msg[0] if msg else '解析失败'}"]
    except (OSError, subprocess.SubprocessError) as e:
        return [f"无法执行 bash 语法检查：{e}"]
    return []


class CodeRunnerTool(BaseTool):
    """把代码落盘后用 ShellTool 执行，继承其全部安全网与授权流程。"""

    name = "code_run"
    description = (
        "运行一段代码并返回输出。支持 python / javascript / typescript / bash。"
        "代码会写入临时文件后执行，需要用户授权——等同于 shell 执行，"
        "因此同样受高危命令判定与授权弹窗约束。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要运行的代码"},
            "language": {
                "type": "string",
                "description": "编程语言 (python/js/ts/bash)",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数",
                "default": 30,
            },
        },
        "required": ["code", "language"],
    }
    cacheable = False  # 有执行副作用，不能缓存
    side_effect = True  # 三方渠道下非主人调用会被守卫拦截
    no_compress = True  # 执行输出要逐字给模型

    def __init__(self) -> None:
        from ethan.tools.builtin.shell import ShellTool

        # 复用同一份高危判定与授权逻辑，避免两套安全策略漂移
        self._shell = ShellTool()

    def _build_command(self, code: str, language: str) -> tuple[str, str] | str:
        """返回 (临时文件路径, 命令串)；语言不支持时返回错误文案。"""
        lang = _normalize_lang(language)
        spec = _LANG_SPECS.get(lang)
        if spec is None:
            return f"不支持的语言：{language}。支持：{', '.join(sorted(_LANG_SPECS))}"

        suffix, runner = spec
        if runner is None:
            return f"{language} 暂不支持执行，只能用 code_analyze 做静态检查。"

        runner_bin = runner[0]
        if shutil.which(runner_bin) is None:
            return (
                f"找不到 {runner_bin}，无法执行 {language}。"
                f"请先安装（如 `npm i -g tsx`）或改用 code_analyze 做静态检查。"
            )

        fd, path = tempfile.mkstemp(suffix=suffix, prefix="ethan_code_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)
        except Exception:
            Path(path).unlink(missing_ok=True)
            raise

        # 用 shlex.quote 兜住路径，避免临时目录含空格时命令被拆断
        cmd = " ".join([*runner, shlex.quote(path)])
        return path, cmd

    async def run(self, code: str, language: str, timeout: int = 30) -> str:
        if not code or not code.strip():
            return "代码为空，无可运行内容。"

        built = self._build_command(code, language)
        if isinstance(built, str):
            return built

        path, cmd = built
        try:
            # 委托 shell：授权弹窗、secret 注入、进程组 kill 全在 ShellTool.run 里
            output = await self._shell.run(cmd, timeout=timeout)
            return f"运行结果（{language}）：\n{output}"
        finally:
            Path(path).unlink(missing_ok=True)

    # ---- 授权：沿用 shell 的判定，但必须连代码正文一起扫 ----
    #
    # 关键安全点：交给 shell 的命令串只有 `python3 /tmp/xxx.py`，代码正文在文件里。
    # 若只把命令串交给 ShellTool.consent_* 扫描，`import os; os.system('rm -rf ~/x')`
    # 这类破坏性代码会完整绕过 _DESTRUCTIVE_RE，被当成普通命令一次授权放行。
    # 因此下面把「命令串 + 代码正文」拼在一起送进 shell 的判定，让正文同样受扫描；
    # 另外用 _code_risk_markers 补 shell 正则识别不了的 API 形态
    # （subprocess.run([...])、shutil.rmtree 等）。

    def _scan_text(self, code: str, language: str) -> str | None:
        """拼出用于高危扫描的文本；该语言无法执行时返回 None（无需授权）。"""
        built = self._build_command(code, language)
        if isinstance(built, str):
            return None
        _, cmd = built
        return f"{cmd}\n{code}"

    def consent_check(self, code: str = "", language: str = "", **kwargs) -> str | None:
        scan = self._scan_text(code, language)
        if scan is None:
            return None
        markers = _code_risk_markers(code, language)
        if markers:
            return (
                f"⚠️ 代码包含可执行任意操作的 API（{', '.join(markers[:3])}），"
                f"将以 {language} 运行，请确认"
            )
        return self._shell.consent_check(command=scan)

    def consent_scope(self, **kwargs) -> str:
        # 与 shell 共用授权作用域：授权过 shell 就等于授权过代码执行，反之亦然
        return self._shell.consent_scope(command="")

    def consent_always(self, code: str = "", language: str = "", **kwargs) -> bool:
        scan = self._scan_text(code, language)
        if scan is None:
            return False
        # 危险 API 命中时始终重新询问，不吃会话级放行
        if _code_risk_markers(code, language):
            return True
        return self._shell.consent_always(command=scan)

    def consent_destructive(self, code: str = "", language: str = "", **kwargs) -> bool:
        scan = self._scan_text(code, language)
        if scan is None:
            return False
        if _code_risk_markers(code, language):
            return True
        return self._shell.consent_destructive(command=scan)
