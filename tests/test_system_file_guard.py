"""system 文件体积护栏 + 心跳 prompt 护栏测试。

线上 badcase：心跳把 gws 检查日志追加进 system/tools.md（自我增殖），
文件涨到 1.7M 字符 ≈ 100 万 token，全文经 <tools_reference> 进每次请求
的 system prompt——单次请求 prompt 逼近上游上限，cache 全 miss。
"""
import os

import pytest

from ethan.core.system_file_guard import (
    DEFAULT_SYSTEM_FILE_MAX_CHARS,
    guard_system_file_content,
    system_file_max_chars,
)
from ethan.core.services.heartbeat import HEARTBEAT_PROMPT_MAX_CHARS, _guard_hb_prompt


class TestSystemFileGuard:
    def test_within_limit_untouched(self):
        """未超限原样返回（不引入任何标记或改写）。"""
        content = "# 工具提示\n\n- rg_search 优先于 shell grep\n"
        assert guard_system_file_content(content, "tools") == content

    def test_over_limit_truncated_keeps_head(self):
        """超限截断保留头部 + 附截断标记。"""
        content = "HEAD-" + "x" * (DEFAULT_SYSTEM_FILE_MAX_CHARS + 1000)
        out = guard_system_file_content(content, "tools")
        assert out.startswith("HEAD-")
        assert len(out) < len(content)
        assert "仅保留前" in out
        assert "被省略" in out
        # 磁盘语义：不改变原内容（调用方负责只把它用于注入）
        assert len(content) == DEFAULT_SYSTEM_FILE_MAX_CHARS + 1005

    def test_exactly_at_limit_not_truncated(self):
        content = "y" * DEFAULT_SYSTEM_FILE_MAX_CHARS
        assert guard_system_file_content(content, "tools") == content

    def test_env_zero_disables(self, monkeypatch):
        monkeypatch.setenv("ETHAN_SYSTEM_FILE_MAX_CHARS", "0")
        assert system_file_max_chars() == 0
        content = "z" * (DEFAULT_SYSTEM_FILE_MAX_CHARS + 5)
        assert guard_system_file_content(content, "tools") == content

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("ETHAN_SYSTEM_FILE_MAX_CHARS", "100")
        out = guard_system_file_content("a" * 200, "tools")
        assert len(out) < 200
        assert out.startswith("a" * 100)

    def test_env_invalid_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ETHAN_SYSTEM_FILE_MAX_CHARS", "abc")
        assert system_file_max_chars() == DEFAULT_SYSTEM_FILE_MAX_CHARS


class TestHeartbeatPromptGuard:
    def _hb_prompt(self, n_log_sections: int = 0, tasks: str = "1  [agent:gmail-watch]\n- 先跑 restore.sh 做健康检查\n") -> str:
        head = "[Heartbeat] 正在执行系统心跳任务：heartbeat.md\n\n"
        logs = "".join(
            f"## gws 健康检查记录（2026-09-{d:02d} 心跳）\n- 日志行 {'x' * 300}\n\n"
            for d in range(1, n_log_sections + 1)
        )
        return head + "# Heartbeat 任务\n\n" + logs + "# 历史记录\n\n" + logs + tasks

    def test_within_limit_untouched(self):
        prompt = self._hb_prompt()
        assert len(prompt) < HEARTBEAT_PROMPT_MAX_CHARS
        assert _guard_hb_prompt(prompt) == prompt

    def test_over_limit_keeps_task_lines_only(self):
        """超限：丢弃日志段，保留 [agent:xxx] 任务行及其缩进指令。"""
        prompt = self._hb_prompt(n_log_sections=80)
        assert len(prompt) > HEARTBEAT_PROMPT_MAX_CHARS
        out = _guard_hb_prompt(prompt)
        assert "[agent:gmail-watch]" in out
        assert "先跑 restore.sh" in out  # 任务指令保留
        assert "gws 健康检查记录" not in out  # 日志段丢弃
        assert "已超 20K 字符上限" in out
        assert len(out) < HEARTBEAT_PROMPT_MAX_CHARS

    def test_over_limit_multiple_tasks(self):
        tasks = (
            "1  [agent:gmail-watch]\n- 检查邮件\n"
            "2  [agent:work-notes]\n- 整理笔记\n"
        )
        prompt = self._hb_prompt(n_log_sections=80, tasks=tasks)
        out = _guard_hb_prompt(prompt)
        assert "[agent:gmail-watch]" in out and "[agent:work-notes]" in out
        assert "检查邮件" in out and "整理笔记" in out
        assert "健康检查记录" not in out

    def test_over_limit_no_task_lines_falls_back_to_head_truncation(self):
        """识别不到任务行时退化为硬截断+重建提示（线上真实发生：日志淹没任务定义）。"""
        prompt = "x" * (HEARTBEAT_PROMPT_MAX_CHARS + 500)
        out = _guard_hb_prompt(prompt)
        assert len(out) > HEARTBEAT_PROMPT_MAX_CHARS  # 头部 + 提示
        assert out.startswith("x" * 100)
        assert "已找不到任何 [agent:xxx] 任务定义行" in out
        assert "重建" in out

    def test_over_limit_log_flooded_file_with_only_dash_lines(self):
        """真实坏例形态：文件由标题 + 大量 '- ' 日志行构成，无任务行。
        截断结果不把日志误判为任务（不进入任务块保留分支）。"""
        logs = "".join(f"## gws 检查（第{i}轮）\n- 日志 {'x' * 200}\n" for i in range(150))
        prompt = "[Heartbeat] 正在执行系统心跳任务：heartbeat.md\n\n" + logs
        assert len(prompt) > HEARTBEAT_PROMPT_MAX_CHARS
        out = _guard_hb_prompt(prompt)
        assert "已找不到任何 [agent:xxx] 任务定义行" in out
        # 硬截断保头：日志被截进来一部分，结尾是重建提示
        assert out.endswith("避免继续膨胀。]")
        # 日志行不以任务块形式重组（没有任务行被保留）
        assert not any("指令" == ln.strip() for ln in out.splitlines())

    def test_task_subsequent_blank_line_ends_task_block(self):
        """任务指令块的缩进行被保留；空行/标题行结束当前任务块。"""
        head = "[Heartbeat] 正在执行系统心跳任务：heartbeat.md\n\n"
        junk = "## 某日志\n" + "- a" * 1 + "\n" + "y" * HEARTBEAT_PROMPT_MAX_CHARS + "\n"
        tasks = "1  [agent:foo]\n- 指令A\n\n## 中间日志\n- 垃圾\n\n2  [agent:bar]\n- 指令B\n"
        prompt = head + junk + tasks
        out = _guard_hb_prompt(prompt)
        assert "[agent:foo]" in out and "指令A" in out
        assert "[agent:bar]" in out and "指令B" in out
        assert "垃圾" not in out
