"""信任目录白名单（tools.trusted_dirs）测试。

覆盖三块：
1. _is_safe_path：白名单目录（含子目录）免授权，兄弟/父目录不放行，
   "/" 条目忽略，~ 展开，.secrets 永不豁免
2. FileWriteTool.consent_check：白名单内写入不再返回授权文案
3. `ethan trust` CLI：add / list / remove / 拒绝根目录
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from ethan.tools.builtin.file import FileWriteTool, _is_safe_path

# 用 home 下的不存在目录做夹具路径：不能用 pytest 的 tmp_path——
# 它在系统临时目录下，本来就会被 /tmp 默认豁免，负例断言会失效
_BASE = Path.home() / ".ethan-test-trusted-dirs"


def _fake_config(trusted_dirs):
    return SimpleNamespace(tools=SimpleNamespace(trusted_dirs=list(trusted_dirs)))


class TestIsSafePath:
    def test_trusted_dir_covers_files_and_subdirs(self):
        d = _BASE / "audio"
        with patch("ethan.core.config.get_config", return_value=_fake_config([str(d)])):
            assert _is_safe_path(str(d / "a.mp3"))
            assert _is_safe_path(str(d / "sub" / "deep" / "b.wav"))
            # 兄弟目录、父目录不放行
            assert not _is_safe_path(str(_BASE / "other" / "c.txt"))
            assert not _is_safe_path(str(_BASE / "d.txt"))

    def test_root_entry_ignored(self):
        # "/" 等于全盘放行，属误配置，应被静默忽略
        with patch("ethan.core.config.get_config", return_value=_fake_config(["/"])):
            assert not _is_safe_path(str(_BASE / "audio" / "a.mp3"))

    def test_home_expansion(self):
        with patch("ethan.core.config.get_config", return_value=_fake_config(["~/.ethan-test-trusted-dirs/audio"])):
            assert _is_safe_path("~/.ethan-test-trusted-dirs/audio/x.mp3")

    def test_secrets_never_exempt(self, tmp_path):
        # .secrets 在白名单目录内也不豁免
        with (
            patch("ethan.core.config.CONFIG_DIR", tmp_path),
            patch("ethan.core.config.get_config", return_value=_fake_config([str(tmp_path)])),
        ):
            assert not _is_safe_path(str(tmp_path / ".secrets" / "api-key"))

    def test_empty_config_unchanged(self):
        with patch("ethan.core.config.get_config", return_value=_fake_config([])):
            assert not _is_safe_path(str(_BASE / "audio" / "a.mp3"))


class TestFileWriteConsent:
    def test_trusted_dir_no_consent_prompt(self):
        d = _BASE / "audio"
        with patch("ethan.core.config.get_config", return_value=_fake_config([str(d)])):
            assert FileWriteTool().consent_check(path=str(d / "a.mp3")) is None

    def test_outside_trusted_dir_still_prompts(self):
        d = _BASE / "audio"
        with patch("ethan.core.config.get_config", return_value=_fake_config([str(d)])):
            assert FileWriteTool().consent_check(path=str(_BASE / "other" / "b.txt")) is not None


class TestTrustCli:
    def test_add_list_remove_roundtrip(self, monkeypatch):
        from ethan.core import config as config_mod
        from ethan.interface.commands import trust as trust_cmd

        cfg = config_mod.Config()
        monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
        saved = []
        monkeypatch.setattr(config_mod, "save_config", lambda c: saved.append(c))

        runner = CliRunner()
        d = _BASE / "audio"

        r = runner.invoke(trust_cmd.app, ["add", str(d)])
        assert r.exit_code == 0, r.output
        assert str(d) in cfg.tools.trusted_dirs
        assert saved and str(d) in saved[-1].tools.trusted_dirs

        # 重复 add 幂等
        r = runner.invoke(trust_cmd.app, ["add", str(d)])
        assert r.exit_code == 0, r.output
        assert cfg.tools.trusted_dirs.count(str(d)) == 1

        r = runner.invoke(trust_cmd.app, ["list"])
        assert r.exit_code == 0, r.output
        assert str(d) in r.output

        r = runner.invoke(trust_cmd.app, ["remove", str(d)])
        assert r.exit_code == 0, r.output
        assert cfg.tools.trusted_dirs == []

    def test_add_rejects_root(self, monkeypatch):
        from ethan.core import config as config_mod
        from ethan.interface.commands import trust as trust_cmd

        cfg = config_mod.Config()
        monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
        monkeypatch.setattr(config_mod, "save_config", lambda c: None)

        runner = CliRunner()
        r = runner.invoke(trust_cmd.app, ["add", "/"])
        assert r.exit_code == 1
        assert cfg.tools.trusted_dirs == []

    def test_remove_not_in_list(self, monkeypatch):
        from ethan.core import config as config_mod
        from ethan.interface.commands import trust as trust_cmd

        cfg = config_mod.Config()
        monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
        monkeypatch.setattr(config_mod, "save_config", lambda c: None)

        runner = CliRunner()
        r = runner.invoke(trust_cmd.app, ["remove", str(_BASE / "nope")])
        assert r.exit_code == 1
