"""时间线持久化 — 路径解析、state 读写、timelines.yaml CRUD。

依赖 ethan.core.config 的 CONFIG_DIR / scene_dir；不依赖 scheduler 或 interface。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

from ethan.core.config import CONFIG_DIR, scene_dir

# scene 路径函数：每个 scene 独立目录（~/.ethan/{scene}/），文件互不干扰。
# 默认 scene 为 "work"（向后兼容）。其他 scene（life/health/...）按需惰性创建。


def _timelines_file(scene: str = "work") -> Path:
    return scene_dir(scene) / "timelines.yaml"


def _state_file(scene: str = "work") -> Path:
    return scene_dir(scene) / ".timeline_state.json"


def _exports_dir(scene: str = "work") -> Path:
    return scene_dir(scene) / "exports"


def _discover_scenes() -> list[str]:
    """扫描 CONFIG_DIR 下所有含 timelines.yaml 的 scene 目录，按字母序返回。

    work/life 预初始化；health/study 等用户自建目录后自动被发现。
    """
    scenes: list[str] = []
    if not CONFIG_DIR.exists():
        return scenes
    for p in CONFIG_DIR.iterdir():
        if p.is_dir() and (p / "timelines.yaml").exists():
            scenes.append(p.name)
    return sorted(scenes)


# ── State persistence ──────────────────────────────────────────────────────

def load_state(scene: str = "work") -> dict:
    sf = _state_file(scene)
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict, scene: str = "work") -> None:
    sf = _state_file(scene)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _fired_key(phase_name: str, action_type: str, idx: int, fire_at: date) -> str:
    return f"{phase_name}_{action_type}_{idx}_{fire_at.isoformat()}"


# ── timelines.yaml CRUD ──────────────────────────────────────────────────────

def get_timelines(scene: str = "work") -> list[dict]:
    """读取某 scene 的 timelines.yaml 中的 timelines 列表。"""
    tf = _timelines_file(scene)
    if not tf.exists():
        return []
    try:
        data = yaml.safe_load(tf.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return data.get("timelines", []) or []


def save_timelines(timelines: list[dict], scene: str = "work") -> None:
    """写回某 scene 的 timelines.yaml。保留 task_categories 等其他字段。"""
    tf = _timelines_file(scene)
    data = {}
    if tf.exists():
        try:
            data = yaml.safe_load(tf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
    data["timelines"] = timelines
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def find_timeline(timeline_id: str) -> tuple[str, Optional[dict]]:
    """在所有 scene 中查找 timeline，返回 (scene, timeline)。未找到返回 (None, None)。"""
    # 空串守卫：否则会误匹配 yaml 中 id 缺失/为空的条目，影响 lifecycle/sync 等下游。
    if not timeline_id:
        return None, None
    for scene in _discover_scenes():
        for tl in get_timelines(scene):
            if tl.get("id") == timeline_id:
                return scene, tl
    return None, None


def upsert_timeline(timeline: dict) -> None:
    """新增或更新（按 id 匹配）一条时间线，写回其 scene 对应文件。

    若 timeline 的 scene 与既有记录不同（跨 scene 迁移），先在旧 scene 清理，
    避免旧 scene 残留同名记录导致主键冲突或状态错乱。
    """
    scene = timeline.get("scene", "work") or "work"
    tl_id = timeline.get("id", "")
    if not tl_id:
        raise ValueError("upsert_timeline: timeline.id 不能为空")
    # 跨 scene 迁移检测：旧记录在别的 scene 里，先删掉再写新 scene
    old_scene, _ = find_timeline(tl_id)
    if old_scene and old_scene != scene:
        remove_timeline(tl_id)
    timelines = get_timelines(scene)
    found = False
    for i, t in enumerate(timelines):
        if t.get("id") == tl_id:
            timelines[i] = timeline
            found = True
            break
    if not found:
        timelines.append(timeline)
    save_timelines(timelines, scene)


def remove_timeline(timeline_id: str) -> bool:
    scene, _ = find_timeline(timeline_id)
    if not scene:
        return False
    timelines = get_timelines(scene)
    new_list = [t for t in timelines if t.get("id") != timeline_id]
    if len(new_list) == len(timelines):
        return False
    save_timelines(new_list, scene)
    # 同时清理 state
    state = load_state(scene)
    state.pop(timeline_id, None)
    save_state(state, scene)
    return True
