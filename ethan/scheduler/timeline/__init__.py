"""时间线引擎 — 将声明式 timelines.yaml 编译为具体的定时任务。

5 步流程（对应 references/timeline-engine.md 的 SOP）：
  1. resolve_anchors          — 计算本周期的锚点日期
  2. determine_current_phase  — 判断今天处于哪个阶段
  3. expand_actions           — 展开动作为 scheduler 任务描述
  4. sync_scheduler           — 同步到 APScheduler（增/删/改）
  5. lifecycle_manage         — 周期轮转 & 手动操作

设计原则：配置（timelines.yaml）描述规则；状态（.timeline_state.json）
记录已发生的事实；两者分离，配置永远有效，状态可重置可迁移。

本模块已拆分为 package，各子模块职责：
  - domain      : 纯计算与数据模型（offset/锚点/阶段/动作展开），零 I/O
  - repository  : 路径解析、state 读写、timelines.yaml CRUD
  - service     : sync_scheduler & lifecycle_manage（scheduler 同步与生命周期）
  - io          : 导入/导出/校验，以及 UI 状态聚合
  - lark_sync   : 飞书日历可视化同步（可选）

此 __init__ 作为兼容门面，保持 `from ethan.scheduler.timeline import X` 不变。
"""
from __future__ import annotations

from .domain import (
    DEFAULT_FIRE_TIME,
    ExpandedTask,
    ResolvedCycle,
    TimelineStatus,
    add_months,
    apply_offset,
    determine_current_phase,
    expand_actions,
    parse_offset,
    resolve_anchors,
)
from .io import (
    export_timelines,
    get_timeline_status,
    import_timelines,
    validate_timelines_file,
)
from .lark_sync import (
    cleanup_lark_resources,
    sync_to_lark,
)
from .repository import (
    find_timeline,
    get_timelines,
    load_state,
    remove_timeline,
    save_state,
    save_timelines,
    upsert_timeline,
)
from .service import (
    lifecycle_manage,
    sync_scheduler,
)

__all__ = [
    # domain — 数据模型
    "ResolvedCycle",
    "ExpandedTask",
    "TimelineStatus",
    "DEFAULT_FIRE_TIME",
    # domain — 纯函数
    "parse_offset",
    "add_months",
    "apply_offset",
    "resolve_anchors",
    "determine_current_phase",
    "expand_actions",
    # repository — CRUD & 持久化
    "get_timelines",
    "save_timelines",
    "find_timeline",
    "upsert_timeline",
    "remove_timeline",
    "load_state",
    "save_state",
    # service — 同步 & 生命周期
    "sync_scheduler",
    "lifecycle_manage",
    # io — 导入/导出/校验/状态
    "get_timeline_status",
    "export_timelines",
    "import_timelines",
    "validate_timelines_file",
    # lark_sync — 飞书可视化
    "sync_to_lark",
    "cleanup_lark_resources",
]
