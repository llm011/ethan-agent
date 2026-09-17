"""`ethan serve` 单实例防护测试。

背景：`ethan serve` 的端口是 CLI 参数（可任意指定），但数据目录（~/.ethan 或
ETHAN_DATA_DIR）是全局共享的。同一数据目录起多个 serve 实例会抢同一个
sessions.db，SQLite 单写者模型下报 `database is locked`，导致定时任务与写入
静默失败。

因此冲突判据是「进程实际打开的 sessions.db 路径是否与当前进程一致」，
而不是「端口是否相同」——两个实例用不同端口照样冲突，用不同 ETHAN_DATA_DIR
则完全无冲突。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from ethan.interface.cli import _find_conflicting_servers


def _fake_proc(stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class TestFindConflictingServers:
    """_find_conflicting_servers() 的核心行为。"""

    def test_no_other_processes(self, tmp_path: Path):
        """pgrep 无输出时，不应报冲突。"""
        with patch("subprocess.run", return_value=_fake_proc(stdout="")), \
             patch("ethan.core.paths.user_sessions_db_path", return_value=tmp_path / "sessions.db"):
            assert _find_conflicting_servers() == []

    def test_detects_same_db_path(self, tmp_path: Path):
        """另一个进程打开同一个 sessions.db 时，应被识别为冲突。"""
        db = tmp_path / "sessions.db"

        def fake_run(cmd, *a, **kw):
            if cmd[0] == "pgrep":
                return _fake_proc(stdout="99999\n")
            if cmd[0] == "lsof":
                # lsof 输出：最后一列是文件路径
                return _fake_proc(stdout=f"python 99999 u 3r REG 0,1 0 12345 {db}\n")
            return _fake_proc()

        with patch("subprocess.run", side_effect=fake_run), \
             patch("ethan.core.paths.user_sessions_db_path", return_value=db):
            conflicts = _find_conflicting_servers()

        assert len(conflicts) == 1
        pid, path = conflicts[0]
        assert pid == 99999
        assert path == str(db)

    def test_different_port_same_db_still_conflicts(self, tmp_path: Path):
        """关键用例：端口不同但 DB 相同 → 仍应判为冲突。

        这是本次修复的核心 —— 之前没有检查，导致 8981/8989 两个实例互锁。
        """
        db = tmp_path / "sessions.db"

        def fake_run(cmd, *a, **kw):
            if cmd[0] == "pgrep":
                # 命令行里端口是 8981，与当前进程 8989 不同
                return _fake_proc(stdout="11111\n")
            if cmd[0] == "lsof":
                return _fake_proc(stdout=f"python 11111 u 3r REG 0,1 0 1 {db}\n")
            return _fake_proc()

        with patch("subprocess.run", side_effect=fake_run), \
             patch("ethan.core.paths.user_sessions_db_path", return_value=db):
            conflicts = _find_conflicting_servers()

        assert len(conflicts) == 1
        assert conflicts[0][0] == 11111

    def test_different_db_path_not_conflict(self, tmp_path: Path):
        """不同数据目录（如 ETHAN_DATA_DIR 隔离）→ 不应报冲突。"""
        my_db = tmp_path / "mine" / "sessions.db"
        other_db = tmp_path / "other" / "sessions.db"

        def fake_run(cmd, *a, **kw):
            if cmd[0] == "pgrep":
                return _fake_proc(stdout="22222\n")
            if cmd[0] == "lsof":
                return _fake_proc(stdout=f"python 22222 u 3r REG 0,1 0 1 {other_db}\n")
            return _fake_proc()

        with patch("subprocess.run", side_effect=fake_run), \
             patch("ethan.core.paths.user_sessions_db_path", return_value=my_db):
            assert _find_conflicting_servers() == []

    def test_journal_suffix_normalized(self, tmp_path: Path):
        """-journal/-wal/-shm 附属文件应归一化回主库路径后比对。

        SQLite 写事务期间 lsof 可能只显示附属文件；若不归一化会漏判 —— 而
        恰恰是「正在写」的实例最需要被检测到。
        """
        db = tmp_path / "sessions.db"

        def fake_run(cmd, *a, **kw):
            if cmd[0] == "pgrep":
                return _fake_proc(stdout="33333\n")
            if cmd[0] == "lsof":
                return _fake_proc(stdout=f"python 33333 u 4u REG 0,1 0 1 {db}-journal\n")
            return _fake_proc()

        with patch("subprocess.run", side_effect=fake_run), \
             patch("ethan.core.paths.user_sessions_db_path", return_value=db):
            conflicts = _find_conflicting_servers()

        assert len(conflicts) == 1
        assert conflicts[0][0] == 33333

    def test_excludes_self(self, tmp_path: Path):
        """不应把自己算作冲突实例。"""
        db = tmp_path / "sessions.db"
        import os

        me = os.getpid()

        def fake_run(cmd, *a, **kw):
            if cmd[0] == "pgrep":
                return _fake_proc(stdout=f"{me}\n")
            if cmd[0] == "lsof":
                return _fake_proc(stdout=f"python {me} u 3r REG 0,1 0 1 {db}\n")
            return _fake_proc()

        with patch("subprocess.run", side_effect=fake_run), \
             patch("ethan.core.paths.user_sessions_db_path", return_value=db):
            assert _find_conflicting_servers() == []

    def test_extra_exclude_pids_filters_legit_server(self, tmp_path: Path):
        """extra_exclude_pids 里的 PID 应被视为合法、不算冲突。

        对应 status 场景：唯一那个健康的常驻 server（记在 server.pid）不是当前
        CLI 进程，传进来排除后就不该出现在冲突列表里。
        """
        db = tmp_path / "sessions.db"

        def fake_run(cmd, *a, **kw):
            if cmd[0] == "pgrep":
                return _fake_proc(stdout="50472\n")
            if cmd[0] == "lsof":
                return _fake_proc(stdout=f"python 50472 u 3r REG 0,1 0 1 {db}\n")
            return _fake_proc()

        with patch("subprocess.run", side_effect=fake_run), \
             patch("ethan.core.paths.user_sessions_db_path", return_value=db):
            # 不排除：正主被误报为冲突（复现 bug）
            assert _find_conflicting_servers() == [(50472, str(db))]
            # 排除正主后：无冲突
            assert _find_conflicting_servers(extra_exclude_pids={50472}) == []

    def test_extra_exclude_pids_still_reports_extras(self, tmp_path: Path):
        """排除正主后，真正多出来的第二个实例仍要被报为冲突。"""
        db = tmp_path / "sessions.db"

        def fake_run(cmd, *a, **kw):
            if cmd[0] == "pgrep":
                return _fake_proc(stdout="50472\n70000\n")
            if cmd[0] == "lsof":
                pid = cmd[cmd.index("-p") + 1]
                return _fake_proc(stdout=f"python {pid} u 3r REG 0,1 0 1 {db}\n")
            return _fake_proc()

        with patch("subprocess.run", side_effect=fake_run), \
             patch("ethan.core.paths.user_sessions_db_path", return_value=db):
            conflicts = _find_conflicting_servers(extra_exclude_pids={50472})

        assert conflicts == [(70000, str(db))]

    def test_extra_exclude_pids_none_is_noop(self, tmp_path: Path):
        """extra_exclude_pids=None 时行为与不传参数一致（向后兼容）。"""
        db = tmp_path / "sessions.db"

        def fake_run(cmd, *a, **kw):
            if cmd[0] == "pgrep":
                return _fake_proc(stdout="88888\n")
            if cmd[0] == "lsof":
                return _fake_proc(stdout=f"python 88888 u 3r REG 0,1 0 1 {db}\n")
            return _fake_proc()

        with patch("subprocess.run", side_effect=fake_run), \
             patch("ethan.core.paths.user_sessions_db_path", return_value=db):
            assert _find_conflicting_servers(extra_exclude_pids=None) == [(88888, str(db))]

    def test_pgrep_failure_is_safe(self, tmp_path: Path):
        """pgrep 抛异常时不应崩溃（返回空列表，允许启动）。"""
        def fake_run(cmd, *a, **kw):
            raise OSError("pgrep not found")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("ethan.core.paths.user_sessions_db_path", return_value=tmp_path / "sessions.db"):
            assert _find_conflicting_servers() == []

    def test_path_resolution_failure_is_safe(self):
        """sessions.db 路径解析失败时不应崩溃。"""
        with patch("ethan.core.paths.user_sessions_db_path", side_effect=RuntimeError("boom")):
            assert _find_conflicting_servers() == []


class TestServeMainForceFlag:
    """--force 应能绕过检测；不带 --force 且有冲突应拒绝启动（exit 1）。"""

    def test_refuses_without_force(self, tmp_path: Path):
        from typer.testing import CliRunner

        from ethan.interface import cli as cli_mod

        runner = CliRunner()
        with patch.object(cli_mod, "_find_conflicting_servers",
                          return_value=[(12345, str(tmp_path / "sessions.db"))]), \
             patch.object(cli_mod, "app", cli_mod.app):
            result = runner.invoke(cli_mod.app, ["serve", "--port", "9999"])

        assert result.exit_code == 1
        assert "拒绝启动" in result.output

    def test_force_bypasses_detection(self, tmp_path: Path):
        """带 --force 时应走到 run_server，而不是被拦截。"""
        from typer.testing import CliRunner

        from ethan.interface import cli as cli_mod

        runner = CliRunner()
        with patch.object(cli_mod, "_find_conflicting_servers",
                          return_value=[(12345, str(tmp_path / "sessions.db"))]), \
             patch("ethan.interface.api.run_server") as mock_run:
            result = runner.invoke(cli_mod.app, ["serve", "--port", "9999", "--force"])

        # 不应因冲突而 exit 1；run_server 应被调用
        assert result.exit_code == 0
        mock_run.assert_called_once_with(host="0.0.0.0", port=9999)
