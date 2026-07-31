"""内置默认技能整树同步（config._sync_skill_tree）测试。

回归背景：旧实现升级时只同步 SKILL.md + references/，scripts/ 从不更新，导致
镜像升级后 render_pptx.py 等脚本停在首次播种的旧版、公式渲染修复静默失效。
这些用例钉住「整树增量同步、只增不删、软链保留、mtime 守护」的行为。
"""
import os
from pathlib import Path

from ethan.core.config import _sync_skill_tree


def _write(p: Path, text: str, mtime: float | None = None):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))


def test_sync_updates_scripts_when_source_newer(tmp_path):
    """核心回归：scripts/ 下源文件更新时，目标必须被覆盖。"""
    src = tmp_path / "src" / "ppt-generate"
    dst = tmp_path / "dst" / "ppt-generate"
    _write(src / "scripts" / "render_pptx.py", "NEW_VERSION_macify", mtime=2000)
    _write(dst / "scripts" / "render_pptx.py", "OLD_VERSION", mtime=1000)

    _sync_skill_tree(src, dst)

    assert (dst / "scripts" / "render_pptx.py").read_text() == "NEW_VERSION_macify"


def test_sync_creates_missing_nested_files(tmp_path):
    """目标缺失的嵌套文件（如新加的 scripts/themes 文件）应被创建。"""
    src = tmp_path / "src" / "ppt-generate"
    dst = tmp_path / "dst" / "ppt-generate"
    _write(src / "SKILL.md", "skill body")
    _write(src / "scripts" / "gen_image.py", "gen")
    _write(src / "themes" / "dark.json", "{}")
    dst.mkdir(parents=True)  # 目标目录已存在但为空

    _sync_skill_tree(src, dst)

    assert (dst / "SKILL.md").read_text() == "skill body"
    assert (dst / "scripts" / "gen_image.py").read_text() == "gen"
    assert (dst / "themes" / "dark.json").read_text() == "{}"


def test_sync_does_not_overwrite_newer_dst(tmp_path):
    """mtime 守护：目标比源新时不覆盖（避免回退用户本地更新的内置文件）。"""
    src = tmp_path / "src" / "ppt-generate"
    dst = tmp_path / "dst" / "ppt-generate"
    _write(src / "scripts" / "render_pptx.py", "SOURCE_OLD", mtime=1000)
    _write(dst / "scripts" / "render_pptx.py", "DST_NEWER", mtime=2000)

    _sync_skill_tree(src, dst)

    assert (dst / "scripts" / "render_pptx.py").read_text() == "DST_NEWER"


def test_sync_preserves_user_added_files(tmp_path):
    """只增不删：用户在目标里新增的文件不被删除。"""
    src = tmp_path / "src" / "ppt-generate"
    dst = tmp_path / "dst" / "ppt-generate"
    _write(src / "SKILL.md", "body")
    _write(dst / "SKILL.md", "old body", mtime=1000)
    _write(dst / "scripts" / "my_custom.py", "user code")

    _sync_skill_tree(src, dst)

    assert (dst / "scripts" / "my_custom.py").read_text() == "user code"


def test_sync_skips_symlinked_dst_file(tmp_path):
    """目标下的软链单文件保留（不覆盖用户挂载的开发副本）。"""
    src = tmp_path / "src" / "ppt-generate"
    dst = tmp_path / "dst" / "ppt-generate"
    _write(src / "scripts" / "render_pptx.py", "FROM_IMAGE", mtime=2000)

    real = tmp_path / "external" / "render_pptx.py"
    _write(real, "DEV_MOUNT", mtime=1000)
    (dst / "scripts").mkdir(parents=True)
    link = dst / "scripts" / "render_pptx.py"
    link.symlink_to(real)

    _sync_skill_tree(src, dst)

    # 软链本身保留、目标内容仍指向开发副本
    assert link.is_symlink()
    assert link.read_text() == "DEV_MOUNT"
    assert real.read_text() == "DEV_MOUNT"
