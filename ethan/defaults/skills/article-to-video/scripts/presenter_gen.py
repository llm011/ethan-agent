#!/usr/bin/env python3
"""presenter_gen.py — article-to-video 虚拟人角色包管理。

角色包 = ~/.ethan/assets/library/presenters/<id>/ 下的 character.json + poses/*.png，
跨视频项目复用（虚拟 IP）。主路径是手动出图：

  1. prompts  打印一整套可直接粘贴的 prompt（角色表 + 逐姿势 prompt + 同会话参考图指引），
              同时把锁定的角色表写入 character.json（status=pending）
  2. 用户在自己的 GPT image 2 会话里出图（先生成姿势 1，再把它传回同一会话做参考逐张换姿势）
  3. import   导入图片目录：尺寸归一 → alpha 嗅探 → 无 alpha 则 Pillow 抠品红底 → status=ready

可选兜底：create 子命令在配了 ETHAN_IMAGE_GEN_* 时走 OpenAI 兼容端点自动生成
（仅 gpt-image-1*/gpt-5-image* 支持 transparent 背景；GPT image 2 等走品红底 + 抠图）。

纯标准库；仅抠图/缩放需要 Pillow（缺失时自动 pip 安装，装不上则 cutout=false 降级，
前端用圆角卡片框渲染，不硬失败）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TIMEOUT = 180
MAX_EDGE = 1536
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# 默认角色属性与姿势短语都是英文：图像模型对英文 prompt 遵循度更高。
DEFAULT_DESCRIPTION = (
    "long dark brown hair, warm brown eyes, white floral blouse with a large bow tie, "
    "soft warm color palette, confident subtle smile"
)
DEFAULT_VOICE = {"name": "zh-CN-XiaoyiNeural", "rate": "+0%", "volume": "+0%", "pitch": "+0Hz"}
DEFAULT_POSES: dict[str, str] = {
    "standing": "standing with hands naturally folded in front, gentle confident smile",
    "explaining": "one hand raised with open palm as if explaining something",
    "pointing": "right hand raised pointing toward the left side, as if pointing at a chart",
    "smiling": "bright cheerful smile with a slight head tilt",
    "thinking": "one finger on chin, thoughtful curious expression",
    "celebrating": "both fists raised slightly in celebration, big happy smile",
}
SHEET_TEMPLATE = (
    "Japanese anime style, half-body portrait illustration of an attractive young woman "
    "financial news presenter, {description}, front three-quarter view, clean cel shading, "
    "crisp edges, upper body centered with headroom, isolated on solid pure magenta "
    "background (#FF00FF), flat uniform background, no text, no watermark, no logo"
)
# 支持 background:"transparent" 的模型前缀（GPT image 2 会拒绝该参数，不能发）。
TRANSPARENT_MODEL_PREFIXES = ("gpt-image-1", "gpt-5-image")


# ---------------------------------------------------------------------------
# 路径与配置
# ---------------------------------------------------------------------------

def data_dir() -> Path:
    override = os.environ.get("ETHAN_DATA_DIR")
    return Path(override).expanduser() if override else Path.home() / ".ethan"


def library_root() -> Path:
    return data_dir() / "assets" / "library"


def presenter_dir(presenter_id: str) -> Path:
    return library_root() / "presenters" / presenter_id


def config_value(name: str) -> str | None:
    """env 优先，再兜底扫 ~/.ethan/.secrets/ 下所有文件的 KEY=value（镜像 secrets_store 格式）。"""
    value = os.environ.get(name)
    if value:
        return value
    secrets_dir = data_dir() / ".secrets"
    if secrets_dir.is_dir():
        for path in sorted(secrets_dir.iterdir()):
            if not path.is_file():
                continue
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("#") or "=" not in stripped:
                        continue
                    key, _, raw = stripped.partition("=")
                    if key.strip() == name:
                        return raw.strip().strip("'\"")
            except OSError:
                continue
    return None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_character(presenter_id: str) -> dict:
    path = presenter_dir(presenter_id) / "character.json"
    if not path.is_file():
        raise SystemExit(f"[error] 角色不存在: {path}（先运行 prompts 子命令）")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_character(presenter_id: str, character: dict) -> None:
    _write_json(presenter_dir(presenter_id) / "character.json", character)


# ---------------------------------------------------------------------------
# prompt 包
# ---------------------------------------------------------------------------

def build_sheet(description: str) -> str:
    return SHEET_TEMPLATE.format(description=description.strip())


def build_pose_prompt(sheet: str, pose_phrase: str, *, first: bool) -> str:
    if first:
        return f"{sheet}. Pose: {pose_phrase}."
    return (
        "Same character as the reference image — identical face, hairstyle, hair color, "
        f"eyes, outfit and art style. Keep the solid pure magenta background (#FF00FF). "
        f"Only change the pose and expression to: {pose_phrase}. Half-body portrait, no text."
    )


def print_prompt_pack(presenter_id: str, character: dict) -> None:
    poses: dict[str, str] = character["posesPrompts"]
    sheet: str = character["sheet"]
    names = list(poses)
    print(f"\n=== 角色「{character['name']}」({presenter_id}) 出图 prompt 包 ===\n")
    print("操作流程（关键：全程在同一个 GPT image 2 会话里，保证角色一致）：\n")
    print(f"  1. 粘贴下面的【姿势 1 / {names[0]}】prompt，生成第一张图")
    print(f"  2. 满意后，把这张图发回同一个会话作为参考图，再粘贴【姿势 2】的 prompt")
    print(f"  3. 之后每个姿势都带上第一张参考图 + 对应 prompt，逐张生成")
    print(f"  4. 全部存进一个目录，文件名改成 <姿势名>.png（如 {names[0]}.png）")
    print(f"  5. 运行: python3 {Path(__file__).resolve()} import {presenter_id} <图片目录>\n")
    print("提示：背景必须是纯品红（#FF00FF），纯色才能自动抠图；")
    print("      某张不满意就在同会话里让它重画，或事后用 regen 子命令重打该姿势的 prompt。\n")
    for index, (name, phrase) in enumerate(poses.items()):
        label = f"姿势 {index + 1} / {name}"
        prompt = build_pose_prompt(sheet, phrase, first=index == 0)
        print(f"----- {label} -----\n{prompt}\n")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# PNG alpha 嗅探与抠图
# ---------------------------------------------------------------------------

def png_has_alpha(path: Path) -> bool:
    """stdlib 读 PNG IHDR：色类型 6=RGBA、4=灰度+alpha，或存在 tRNS 块。非 PNG 返回 False。"""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 33:
        return False
    color_type = data[25]
    if color_type in (4, 6):
        return True
    return b"tRNS" in data[:65536]


def _pip_install(*packages: str) -> bool:
    print(f"  [info] 安装依赖 {' '.join(packages)} ...", file=sys.stderr)
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", *([] if in_venv else ["--user"]), *packages]
    try:
        subprocess.check_call(cmd)
        import site

        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.append(user_site)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 自动安装失败: {exc}", file=sys.stderr)
        return False


def _pillow():
    try:
        from PIL import Image

        return Image
    except ImportError:
        pass
    for attempt in range(2):
        try:
            from PIL import Image

            return Image
        except ImportError:
            if attempt == 0 and _pip_install("pillow"):
                continue
            return None
    return None


def cutout_to_png(src: Path, dst: Path, *, tolerance: int = 42) -> bool:
    """边缘泛洪抠图：以边缘采样色为 key，从四边 BFS 把背景像素 alpha 置 0。

    品红底（或任何近纯色底）都适用；发丝等复杂边缘可能有少量残留，动漫立绘可接受。
    """
    Image = _pillow()
    if Image is None:
        return False
    try:
        img = Image.open(src).convert("RGBA")
        if max(img.size) > MAX_EDGE:
            img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        width, height = img.size
        pixels = img.load()
        step_x = max(1, width // 60)
        step_y = max(1, height // 60)
        samples = []
        for x in range(0, width, step_x):
            samples.append(pixels[x, 0][:3])
            samples.append(pixels[x, height - 1][:3])
        for y in range(0, height, step_y):
            samples.append(pixels[0, y][:3])
            samples.append(pixels[width - 1, y][:3])
        key = tuple(sorted(c[i] for c in samples)[len(samples) // 2] for i in range(3))
        tolerance_sq = (tolerance * 3) ** 2

        # 走原始字节（getdata/putdata 在 Pillow 12+ 已弃用）：匹配掩码 + BFS + putalpha。
        raw = img.tobytes()
        pixel_count = width * height
        matches = bytearray(pixel_count)
        kr, kg, kb = key
        for i in range(pixel_count):
            offset = i * 4
            dr = raw[offset] - kr
            dg = raw[offset + 1] - kg
            db = raw[offset + 2] - kb
            if dr * dr + dg * dg + db * db <= tolerance_sq:
                matches[i] = 1

        visited = bytearray(pixel_count)
        alpha = bytearray(b"\xff") * pixel_count
        queue: list[int] = []
        for x in range(width):
            queue.extend((x, x + (height - 1) * width))
        for y in range(height):
            queue.extend((y * width, width - 1 + y * width))
        head = 0
        while head < len(queue):
            index = queue[head]
            head += 1
            if visited[index] or not matches[index]:
                continue
            visited[index] = 1
            alpha[index] = 0
            x, y = index % width, index // width
            if x > 0:
                queue.append(index - 1)
            if x < width - 1:
                queue.append(index + 1)
            if y > 0:
                queue.append(index - width)
            if y < height - 1:
                queue.append(index + width)
        img.putalpha(Image.frombytes("L", (width, height), bytes(alpha)))
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "PNG")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 抠图失败 {src.name}: {exc}", file=sys.stderr)
        return False


def normalize_image(src: Path, dst: Path) -> bool:
    """已带 alpha 的图：仅做尺寸归一后转 PNG；无 Pillow 时原样拷贝。"""
    Image = _pillow()
    if Image is None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    try:
        img = Image.open(src)
        if max(img.size) > MAX_EDGE:
            img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "PNG")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 图片处理失败 {src.name}: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# import：导入用户出图
# ---------------------------------------------------------------------------

def match_pose_files(image_dir: Path, pose_names: list[str]) -> dict[str, Path]:
    """文件名匹配姿势：精确词干 → 包含匹配 → 剩余文件按排序补齐剩余姿势。"""
    files = sorted(p for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    assigned: dict[str, Path] = {}
    used: set[Path] = set()
    for name in pose_names:
        for path in files:
            if path not in used and path.stem.lower() == name:
                assigned[name] = path
                used.add(path)
                break
    for name in pose_names:
        if name in assigned:
            continue
        for path in files:
            if path not in used and name in path.stem.lower():
                assigned[name] = path
                used.add(path)
                break
    remaining_poses = [name for name in pose_names if name not in assigned]
    remaining_files = [path for path in files if path not in used]
    for name, path in zip(remaining_poses, remaining_files):
        assigned[name] = path
        print(f"  [info] {path.name} 按顺序匹配到姿势 {name}", file=sys.stderr)
    return assigned


def cmd_import(presenter_id: str, image_dir: Path) -> None:
    character = _load_character(presenter_id)
    pose_names = list(character.get("posesPrompts") or DEFAULT_POSES)
    if not image_dir.is_dir():
        raise SystemExit(f"[error] 图片目录不存在: {image_dir}")
    assigned = match_pose_files(image_dir, pose_names)
    missing = [name for name in pose_names if name not in assigned]
    if missing:
        raise SystemExit(f"[error] 目录里没有可匹配的图片，缺少姿势: {', '.join(missing)}")

    dest_dir = presenter_dir(presenter_id) / "poses"
    poses: dict[str, str] = {}
    all_cutout = True
    for name, src in assigned.items():
        dst = dest_dir / f"{name}.png"
        if png_has_alpha(src):
            ok = normalize_image(src, dst)
            cut = True
        else:
            print(f"  [info] {src.name} 无 alpha，尝试抠图 ...", file=sys.stderr)
            ok = cutout_to_png(src, dst)
            cut = ok
            if not ok:
                # 抠不动也能用：原样拷贝，前端用卡片框渲染。
                ok = normalize_image(src, dst)
        if not ok:
            raise SystemExit(f"[error] 处理失败: {src}")
        all_cutout = all_cutout and cut
        poses[name] = f"poses/{name}.png"
        print(f"  [ok] {name} <- {src.name}{'' if cut else '（未抠图，卡片框降级）'}")

    character["poses"] = poses
    character["cutout"] = all_cutout
    character["status"] = "ready"
    character["source"] = character.get("source") or "manual"
    _save_character(presenter_id, character)
    print(f"\n[ok] 角色「{character['name']}」已就绪: {presenter_dir(presenter_id)}")
    print(f"     姿势: {', '.join(poses)}；抠图: {'是' if all_cutout else '否（卡片框渲染）'}")
    print(f"     现在可以在 manifest 里引用: \"presenter\": {{\"id\": \"{presenter_id}\"}}")


# ---------------------------------------------------------------------------
# prompts / regen
# ---------------------------------------------------------------------------

def _validate_id(presenter_id: str) -> None:
    if not ID_RE.fullmatch(presenter_id):
        raise SystemExit(f"[error] 角色 id 必须是 kebab-case: {presenter_id}")


def _parse_pose_overrides(raw: str | None) -> dict[str, str]:
    if not raw:
        return dict(DEFAULT_POSES)
    poses: dict[str, str] = {}
    for item in raw.split(","):
        name = item.strip()
        if not name:
            continue
        if not ID_RE.fullmatch(name):
            raise SystemExit(f"[error] 姿势名必须是 kebab-case: {name}")
        if name not in DEFAULT_POSES:
            print(f"  [warn] 未知姿势 {name}，使用泛化姿势短语", file=sys.stderr)
        poses[name] = DEFAULT_POSES.get(name, f"in a {name} pose")
    if not poses:
        raise SystemExit("[error] --poses 解析后为空")
    return poses


def cmd_prompts(presenter_id: str, args: argparse.Namespace) -> None:
    _validate_id(presenter_id)
    existing = presenter_dir(presenter_id) / "character.json"
    if existing.is_file() and not args.force:
        raise SystemExit(f"[error] 角色 {presenter_id} 已存在（--force 可覆盖重建）")
    description = (args.description or DEFAULT_DESCRIPTION).strip()
    poses_prompts = _parse_pose_overrides(args.poses)
    character = {
        "id": presenter_id,
        "name": args.name or presenter_id,
        "status": "pending",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "description": description,
        "sheet": build_sheet(description),
        "posesPrompts": poses_prompts,
        "voice": DEFAULT_VOICE,
        "poses": {},
        "cutout": True,
        "source": None,
        "attribution": "user-generated with GPT image 2",
    }
    _save_character(presenter_id, character)
    print_prompt_pack(presenter_id, character)


def cmd_regen(presenter_id: str, pose: str) -> None:
    character = _load_character(presenter_id)
    poses_prompts: dict[str, str] = character.get("posesPrompts") or {}
    if pose not in poses_prompts:
        raise SystemExit(f"[error] 未知姿势 {pose}，可选: {', '.join(poses_prompts)}")
    print("在同一会话里带上第一张立绘参考图，粘贴：\n")
    print(build_pose_prompt(character["sheet"], poses_prompts[pose], first=False))
    print(f"\n生成后覆盖 <图片目录>/{pose}.png 并重新运行 import。")


# ---------------------------------------------------------------------------
# create：API 自动生成（可选兜底）
# ---------------------------------------------------------------------------

def _image_gen_request(prompt: str, dest: Path, *, transparent_ok: bool) -> bool:
    api_key = config_value("ETHAN_IMAGE_GEN_API_KEY")
    if not api_key:
        print("[error] 未配置 ETHAN_IMAGE_GEN_API_KEY（env 或 ~/.ethan/.secrets/）", file=sys.stderr)
        return False
    base = (config_value("ETHAN_IMAGE_GEN_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = config_value("ETHAN_IMAGE_GEN_MODEL") or "gpt-image-1"
    payload: dict = {"model": model, "prompt": prompt, "n": 1, "size": "1024x1536"}
    if transparent_ok:
        payload["background"] = "transparent"
        payload["output_format"] = "png"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/images/generations",
        data=body,
        headers={"User-Agent": UA, "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        item = (data.get("data") or [{}])[0]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if item.get("b64_json"):
            import base64

            dest.write_bytes(base64.b64decode(item["b64_json"]))
            return True
        if item.get("url"):
            with urllib.request.urlopen(
                urllib.request.Request(item["url"], headers={"User-Agent": UA}), timeout=TIMEOUT
            ) as resp:
                dest.write_bytes(resp.read())
            return True
        print(f"  [warn] 生图响应无 b64_json/url: {str(data)[:200]}", file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 生图失败: {exc}", file=sys.stderr)
        return False


def cmd_create(presenter_id: str, args: argparse.Namespace) -> None:
    _validate_id(presenter_id)
    model = (config_value("ETHAN_IMAGE_GEN_MODEL") or "gpt-image-1").lower()
    transparent_ok = model.startswith(TRANSPARENT_MODEL_PREFIXES) and not model.startswith("gpt-image-2")
    if not transparent_ok:
        print(f"  [info] 模型 {model} 不支持透明背景，走品红底 + 导入抠图", file=sys.stderr)
    if not (presenter_dir(presenter_id) / "character.json").is_file() or args.force:
        description = (args.description or DEFAULT_DESCRIPTION).strip()
        character = {
            "id": presenter_id,
            "name": args.name or presenter_id,
            "status": "pending",
            "createdAt": datetime.now().isoformat(timespec="seconds"),
            "description": description,
            "sheet": build_sheet(description),
            "posesPrompts": _parse_pose_overrides(args.poses),
            "voice": DEFAULT_VOICE,
            "poses": {},
            "cutout": True,
            "source": "api",
            "attribution": f"generated via {model}",
        }
        _save_character(presenter_id, character)
    character = _load_character(presenter_id)
    staging = presenter_dir(presenter_id) / "work" / "raw"
    prompts = {
        name: build_pose_prompt(character["sheet"], phrase, first=index == 0)
        for index, (name, phrase) in enumerate(character["posesPrompts"].items())
    }
    for name, prompt in prompts.items():
        dest = staging / f"{name}.png"
        if dest.exists():
            continue
        print(f"  [info] 生成姿势 {name} ...", file=sys.stderr)
        if not _image_gen_request(prompt, dest, transparent_ok=transparent_ok):
            raise SystemExit(f"[error] 姿势 {name} 生成失败，可重试（已生成的会跳过）")
    cmd_import(presenter_id, staging)


# ---------------------------------------------------------------------------
# list / show
# ---------------------------------------------------------------------------

def cmd_list() -> None:
    root = library_root() / "presenters"
    if not root.is_dir():
        print(f"[ok] 还没有角色（库目录: {root}）")
        return
    rows = []
    for char_path in sorted(root.glob("*/character.json")):
        try:
            character = json.loads(char_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        poses = character.get("poses") or {}
        rows.append(
            f"  {character.get('id', char_path.parent.name):<16} "
            f"status={character.get('status', '?'):<8} "
            f"poses={len(poses):<3} cutout={character.get('cutout', '?')} "
            f"voice={(character.get('voice') or {}).get('name', '-')}"
        )
    print(f"角色库: {root}\n" + ("\n".join(rows) if rows else "  （空）"))


def cmd_show(presenter_id: str) -> None:
    character = _load_character(presenter_id)
    print(json.dumps(character, ensure_ascii=False, indent=2))
    if character.get("status") != "ready":
        print_prompt_pack(presenter_id, character)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="article-to-video 虚拟人角色包管理（GPT image 2 手动出图 + 导入）")
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("id", help="角色 id（kebab-case，如 xiaoyu）")
        p.add_argument("--description", help="角色外观描述（英文，覆盖默认属性）")
        p.add_argument("--poses", help="逗号分隔的姿势清单（默认 6 个标准姿势）")
        p.add_argument("--name", help="角色显示名（默认同 id）")
        p.add_argument("--force", action="store_true", help="覆盖已有角色包")

    _common(sub.add_parser("prompts", help="打印出图 prompt 包并初始化角色（pending）"))
    _common(sub.add_parser("create", help="可选兜底：调 OpenAI 兼容端点自动生成"))

    import_cmd = sub.add_parser("import", help="导入出图目录，抠图并置为 ready")
    import_cmd.add_argument("id")
    import_cmd.add_argument("dir", type=Path, help="图片目录（文件名按姿势名匹配）")

    regen = sub.add_parser("regen", help="重新打印单个姿势的 prompt")
    regen.add_argument("id")
    regen.add_argument("pose")

    sub.add_parser("list", help="列出角色库")
    show = sub.add_parser("show", help="查看角色详情")
    show.add_argument("id")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "prompts":
        cmd_prompts(args.id, args)
    elif args.command == "create":
        cmd_create(args.id, args)
    elif args.command == "import":
        cmd_import(args.id, args.dir.expanduser().resolve())
    elif args.command == "regen":
        cmd_regen(args.id, args.pose)
    elif args.command == "list":
        cmd_list()
    elif args.command == "show":
        cmd_show(args.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
