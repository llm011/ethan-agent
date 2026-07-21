"""时区工具：解析系统时区 / 配置时区，供调度器、心跳等全链路使用。"""


def _resolve_tz(tz_str: str = ""):
    """将 IANA 时区名或空串解析为 tzinfo。

    优先级：
    1. tz_str 非空 → ZoneInfo(tz_str)
    2. /etc/localtime 软链（macOS / Linux）→ 自动读 IANA 名
    3. 回退到 Python 本地偏移（datetime.now().astimezone().tzinfo）
    """
    if tz_str:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_str)

    # 尝试 TZ 环境变量（Docker 场景常用）
    import os
    env_tz = os.environ.get("TZ", "")
    if env_tz and env_tz != "UTC":
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(env_tz)
        except Exception:
            pass

    # 尝试从系统符号链接读 IANA 名
    try:
        tz_path = os.readlink("/etc/localtime")
        if "zoneinfo/" in tz_path:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_path.split("zoneinfo/")[-1])
    except Exception:
        pass

    # 回退：用当前本地偏移（固定偏移，无 DST 信息）
    from datetime import datetime
    return datetime.now().astimezone().tzinfo


def get_local_timezone():
    """读取 config.defaults.timezone，空则自动探测系统时区。"""
    try:
        from ethan.core.config import get_config
        tz_str = get_config().defaults.timezone
    except Exception:
        tz_str = ""
    try:
        return _resolve_tz(tz_str)
    except Exception:
        return _resolve_tz("")


def ensure_timezone_in_config() -> None:
    """确保 config.defaults.timezone 已持久化。

    若为空，则探测系统时区并写回 config.yaml，避免后续因环境变化（Docker、
    远程部署等）导致时区探测结果不一致。
    """
    try:
        from ethan.core.config import get_config, save_config
        cfg = get_config()
        if cfg.defaults.timezone:
            return  # 已显式配置，无需操作
        tz = _resolve_tz("")
        tz_name = getattr(tz, "key", None)  # ZoneInfo 有 .key
        if not tz_name:
            # 固定偏移时区无 IANA 名 → 用 UTC 偏移推断常见时区作为兜底
            import logging
            from datetime import datetime
            try:
                offset = datetime.now(tz).utcoffset()
                total_hours = int(offset.total_seconds() // 3600)
                # 常见偏移 → IANA 映射
                _OFFSET_FALLBACK = {
                    8: "Asia/Shanghai", 9: "Asia/Tokyo", -5: "America/New_York",
                    -8: "America/Los_Angeles", 0: "UTC", 1: "Europe/London",
                    5: "Asia/Karachi",
                }
                tz_name = _OFFSET_FALLBACK.get(total_hours)
            except Exception:
                pass
            if not tz_name:
                logging.getLogger(__name__).info(
                    "Cannot determine IANA timezone from system; "
                    "set defaults.timezone in config.yaml manually."
                )
                return
        cfg.defaults.timezone = tz_name
        save_config(cfg)
    except Exception:
        pass  # 首次启动时 config 可能尚未就绪，静默忽略


def local_tz_name() -> str:
    """返回可读时区名称，用于展示给用户（如 'Asia/Shanghai' 或 'UTC+08:00'）。"""
    tz = get_local_timezone()
    key = getattr(tz, "key", None)  # ZoneInfo 有 .key
    if key:
        return key
    # 固定偏移时区
    try:
        from datetime import datetime
        offset = datetime.now(tz).utcoffset()
        total_minutes = int(offset.total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        h, m = divmod(abs(total_minutes), 60)
        return f"UTC{sign}{h:02d}:{m:02d}"
    except Exception:
        return str(tz)
