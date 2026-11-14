r"""code_assistant 工具的回归测试。

覆盖三件事（这三件事正是 v2 PR 里那个「5/5 全绿」假检查没覆盖的）：

1. **真的能跑**：code_analyze 检查语法、code_run 真的出结果；
2. **真的注册了**：build_tool_registry 里能看到两个工具名，而不只是类存在；
3. **安全网不漏**：code_run 把代码写进临时文件后交给 shell 执行，若只扫命令串
   （`python3 /tmp/xxx.py`），破坏性代码正文会完整绕过高危判定。这里锁定
   「正文里的危险 API 也必须被判 destructive」。
"""
from __future__ import annotations

import asyncio

import pytest

from ethan.tools.builtin.code_assistant import (
    CodeAssistantTool,
    CodeRunnerTool,
    _code_risk_markers,
)


@pytest.fixture(scope="module")
def analyzer() -> CodeAssistantTool:
    return CodeAssistantTool()


@pytest.fixture(scope="module")
def runner() -> CodeRunnerTool:
    return CodeRunnerTool()


# ── 工具元信息 ────────────────────────────────────────────────

def test_tool_names(analyzer, runner):
    assert analyzer.name == "code_analyze"
    assert runner.name == "code_run"


def test_runner_is_side_effect_and_uncacheable(runner):
    """code_run 有执行副作用：三方渠道守卫靠 side_effect 拦非主人调用。"""
    assert runner.side_effect is True
    assert runner.cacheable is False


def test_analyzer_is_readonly(analyzer):
    assert analyzer.side_effect is False


def test_tools_actually_registered():
    """类存在 ≠ 注册了。这一条替代原来那个只检查 tool.name 的假检查。"""
    from ethan.core.agent_factory import build_tool_registry

    names = {t.name for t in build_tool_registry(channel="repl").all()}
    assert "code_analyze" in names
    assert "code_run" in names


# ── code_analyze 功能 ────────────────────────────────────────

def test_analyze_valid_python(analyzer):
    out = asyncio.run(analyzer.run(code="def hello():\n    return 1", language="python"))
    assert "通过" in out
    assert "错误" not in out


def test_analyze_syntax_error(analyzer):
    out = asyncio.run(analyzer.run(code="def bad(:\n    pass", language="python"))
    assert "语法错误" in out


def test_analyze_flags_bare_except(analyzer):
    out = asyncio.run(analyzer.run(code="try:\n    pass\nexcept:\n    pass", language="python"))
    assert "裸 except" in out


def test_analyze_empty_code(analyzer):
    assert "为空" in asyncio.run(analyzer.run(code="  ", language="python"))


def test_analyze_unknown_language_does_not_crash(analyzer):
    out = asyncio.run(analyzer.run(code="x = 1", language="cobol"))
    assert "暂不支持" in out


# ── code_run 功能 ───────────────────────────────────────────

def test_run_python(runner):
    out = asyncio.run(runner.run(code="print(1 + 1)", language="python", timeout=20))
    assert "2" in out


def test_run_python_captures_error(runner):
    out = asyncio.run(runner.run(code="raise ValueError('boom')", language="python", timeout=20))
    assert "boom" in out


def test_run_unsupported_language(runner):
    out = asyncio.run(runner.run(code="x", language="cobol"))
    assert "不支持的语言" in out


def test_run_empty_code(runner):
    assert "为空" in asyncio.run(runner.run(code="", language="python"))


def test_run_cleans_up_temp_file(runner, tmp_path):
    """执行后临时文件必须删掉，不能留一地 ethan_code_* 垃圾。"""
    import glob
    import tempfile

    before = set(glob.glob(f"{tempfile.gettempdir()}/ethan_code_*"))
    asyncio.run(runner.run(code="x = 1", language="python", timeout=20))
    after = set(glob.glob(f"{tempfile.gettempdir()}/ethan_code_*"))
    assert after - before == set()


# ── 安全网：代码正文必须走高危判定 ────────────────────────────

@pytest.mark.parametrize(
    "code,language",
    [
        ("import os; os.system('rm -rf ~/foo')", "python"),
        # 参数被拆成列表元素，`rm ` 不再以空格相邻，shell 正则匹配不到——靠 API 名扫描兜住
        ("subprocess.run(['rm', '-rf', '/'])", "python"),
        ("import shutil; shutil.rmtree('/data')", "python"),
        ("os.system('dd if=/dev/zero of=/dev/sda')", "python"),
        ("require('child_process').execSync('rm -rf /')", "javascript"),
    ],
)
def test_dangerous_code_is_destructive(runner, code, language):
    assert runner.consent_destructive(code=code, language=language) is True
    # 破坏性操作即使会话内授权过 shell，也必须重新问
    assert runner.consent_always(code=code, language=language) is True


@pytest.mark.parametrize(
    "code,language",
    [
        ("print(1 + 1)", "python"),
        ("def add(a, b):\n    return a + b", "python"),
        ("console.log('hi')", "javascript"),
    ],
)
def test_safe_code_not_destructive(runner, code, language):
    assert runner.consent_destructive(code=code, language=language) is False


def test_unececutable_language_needs_no_consent(runner):
    """语言无法执行时不会真的跑，不该弹授权。"""
    assert runner.consent_check(code="x", language="cobol") is None


def test_consent_scope_shared_with_shell(runner):
    """与 shell 共用一个授权作用域，避免两套策略各自累积授权。"""
    from ethan.tools.builtin.shell import ShellTool

    assert runner.consent_scope() == ShellTool().consent_scope(command="")


def test_risk_markers_helper():
    assert _code_risk_markers("print(1)", "python") == []
    assert "os.system" in _code_risk_markers("os.system('x')", "python")
    assert _code_risk_markers("whatever", "cobol") == []
