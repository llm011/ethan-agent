"""scripts/setup_dsh_tui_theme.py 的 profile patch 写入行为。

只测最容易回归的那块：marker 块的重写必须幂等、不吞块外内容、
fullscreen 开关可来回切换。
"""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_dsh_tui_theme.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("setup_dsh_tui_theme", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def patch_file(mod, tmp_path):
    p = tmp_path / "cordis.patch.yml"
    p.write_text("# 别的 patch\n- id: other\n  config:\n    a: 1\n", encoding="utf-8")
    mod.PROFILE_PATCH = p
    return p


def test_default_is_fullscreen(mod, patch_file):
    mod._write_profile_patch()
    text = patch_file.read_text(encoding="utf-8")
    assert "fullscreen: true" in text
    assert "# 别的 patch" in text
    assert text.count(mod.MARKER) == 1


def test_inline_and_back_is_idempotent(mod, patch_file):
    mod._write_profile_patch()
    once = patch_file.read_text(encoding="utf-8")

    mod._write_profile_patch(False)
    inline = patch_file.read_text(encoding="utf-8")
    assert "fullscreen: false" in inline
    assert "fullscreen: true" not in inline
    assert inline.count(mod.MARKER) == 1
    assert "# 别的 patch" in inline

    mod._write_profile_patch(True)
    back = patch_file.read_text(encoding="utf-8")
    assert back == once


def test_missing_anchor_raises_without_overwrite(mod, patch_file):
    patch_file.write_text(mod.MARKER + "\n手改过的块\n", encoding="utf-8")
    before = patch_file.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        mod._write_profile_patch()
    assert patch_file.read_text(encoding="utf-8") == before
