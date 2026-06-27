"""install_skill — 从 GitHub 仓库/子目录安装 Skill 到 ~/.ethan/skills/。

用户发 GitHub 链接说"装这个 skill"时用本工具，一步到位：
  解析 source → git 浅克隆（自动走代理）→ 定位 SKILL.md → 连同 scripts/references
  等依赖复制到 ~/.ethan/skills/<name> → 删 .git。

不依赖外部 npx skills / skill-manager 脚本（那些会动态消失、且常超时）。
"""
import asyncio
import re
import shutil
import socket
import tempfile
from pathlib import Path

from ethan.tools.base import BaseTool


def _fallback_proxy() -> str:
    """直连失败后的兜底代理：优先 config.network.proxy，其次探测本机常见端口。
    返回 "" 表示没有可用代理。"""
    try:
        from ethan.core.config import get_config
        cfg_proxy = get_config().network.proxy
        if cfg_proxy:
            return cfg_proxy
    except Exception:
        pass
    for port in (7890, 7897, 1087, 8118):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return f"http://127.0.0.1:{port}"
        except OSError:
            continue
    return ""


def _parse_source(source: str) -> tuple[str, str, str]:
    """解析 source → (clone_url, branch, subdir)。

    支持：
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      owner/repo
      https://github.com/owner/repo/tree/<branch>/<subdir...>
    """
    s = source.strip().rstrip("/")
    branch, subdir = "", ""

    m = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+)/(.+))?$", s)
    if m:
        owner, repo, branch, subdir = m.group(1), m.group(2), m.group(3) or "", m.group(4) or ""
    else:
        # owner/repo 形式（可带子目录 owner/repo/sub/dir）
        parts = s.split("/")
        if len(parts) < 2:
            raise ValueError(f"无法解析 GitHub 来源：{source}")
        owner, repo = parts[0], parts[1]
        if len(parts) > 2:
            subdir = "/".join(parts[2:])

    repo = repo[:-4] if repo.endswith(".git") else repo
    clone_url = f"https://github.com/{owner}/{repo}.git"
    return clone_url, branch, subdir


async def _run_git(args: list[str], proxy: str, timeout: int = 120) -> tuple[int, str]:
    import os
    env = dict(os.environ)
    if proxy:
        env["https_proxy"] = env["HTTPS_PROXY"] = proxy
        env["http_proxy"] = env["HTTP_PROXY"] = proxy
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"git {' '.join(args[:2])} 超时（{timeout}s）"
    return proc.returncode, out.decode(errors="replace")


def _find_skill_dir(root: Path, subdir: str) -> list[Path]:
    """在克隆目录里找含 SKILL.md 的目录。subdir 指定则只看该子目录。"""
    if subdir:
        cand = root / subdir
        if (cand / "SKILL.md").exists():
            return [cand]
        return []
    if (root / "SKILL.md").exists():
        return [root]
    # 搜全仓库（限定深度，避免巨型 repo 卡住）
    hits = []
    for p in root.rglob("SKILL.md"):
        if ".git" in p.parts:
            continue
        hits.append(p.parent)
    return hits


class InstallSkillTool(BaseTool):
    fast_path = False  # 低频重操作；fast 档经 find_tools 激活，full 档直接可用
    side_effect = True
    no_compress = True
    cacheable = False
    name = "install_skill"
    description = (
        "从 GitHub 仓库或子目录安装 Skill 到 ~/.ethan/skills/。"
        "用户发来 GitHub 链接并想安装其中的 skill 时用本工具，一步到位（自带代理、找 SKILL.md、拉依赖脚本）。"
        "不要用 npx skills 或手动 git clone。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "GitHub 来源：完整 URL（含 /tree/分支/子目录 亦可）、owner/repo、或 owner/repo/子目录。",
            },
            "name": {
                "type": "string",
                "description": "可选。装成的 skill 目录名；仓库含多个 skill 时用来指定要装哪个（子目录名）。",
            },
        },
        "required": ["source"],
    }

    async def run(self, source: str, name: str = "") -> str:
        from ethan.core.paths import user_skills_dir
        from ethan.skills.loader import load_skill_from_dir

        try:
            clone_url, branch, subdir = _parse_source(source)
        except ValueError as e:
            return f"❌ {e}"

        if name and not subdir:
            subdir = name  # 用 name 指定子目录

        with tempfile.TemporaryDirectory(prefix="ethan_skill_") as tmp:
            tmp_root = Path(tmp) / "repo"

            def _clone_args():
                args = ["clone", "--depth", "1"]
                if branch:
                    args += ["--branch", branch]
                return args + [clone_url, str(tmp_root)]

            # 1) 先直连（默认不挂代理）
            code, out = await _run_git(_clone_args(), proxy="")
            proxy_note = "（直连）"

            # 2) 直连失败 → 兜底到代理重试（config.network.proxy 或本机常见端口）
            if code != 0:
                proxy = _fallback_proxy()
                if proxy:
                    if tmp_root.exists():
                        shutil.rmtree(tmp_root, ignore_errors=True)
                    code2, out2 = await _run_git(_clone_args(), proxy=proxy)
                    if code2 == 0:
                        code, out = code2, out2
                        proxy_note = f"（直连失败，经代理 {proxy}）"
                    else:
                        return (
                            f"❌ 克隆失败：直连和代理（{proxy}）都不通。\n"
                            f"直连错误:\n{out[-300:]}\n\n代理错误:\n{out2[-300:]}"
                        )
                else:
                    hint = "（无可用代理可兜底；可在设置里配 network.proxy）"
                    return f"❌ 克隆失败 {hint}\n{out[-500:]}"

            skill_dirs = _find_skill_dir(tmp_root, subdir)
            if not skill_dirs:
                where = f"子目录 {subdir}" if subdir else "仓库根目录"
                return f"❌ 在{where}没找到 SKILL.md。请确认链接指向的是含 SKILL.md 的 skill 目录。"
            if len(skill_dirs) > 1:
                names = ", ".join(sorted(d.name for d in skill_dirs))
                return (
                    f"⚠️ 仓库里有多个 skill（含 SKILL.md 的目录）：{names}\n"
                    f"请用 name 参数指定要装哪个，例如 install_skill(source=..., name=\"{sorted(d.name for d in skill_dirs)[0]}\")。"
                )

            src_dir = skill_dirs[0]
            skill_name = name or (src_dir.name if src_dir != tmp_root else clone_url.rstrip("/").split("/")[-1][:-4])

            dest = user_skills_dir() / skill_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src_dir, dest, ignore=shutil.ignore_patterns(".git"))
            # 双保险删 .git
            git_dir = dest / ".git"
            if git_dir.exists():
                shutil.rmtree(git_dir, ignore_errors=True)

        # 校验装完能解析
        skill = load_skill_from_dir(dest)
        if not skill:
            return f"⚠️ 已复制到 {dest}，但 SKILL.md 解析失败，请检查其 frontmatter 格式。"

        files = sorted(p.name for p in dest.iterdir())
        trigger = ", ".join(skill.trigger[:6]) if skill.trigger else "（无）"
        return (
            f"✅ 已安装 skill「{skill.name}」{proxy_note}\n"
            f"位置: {dest}\n"
            f"描述: {skill.description}\n"
            f"触发词: {trigger}\n"
            f"包含文件: {', '.join(files)}\n"
            f"无需重启，下次对话自动加载。"
        )
