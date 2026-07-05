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

    # 尝试从系统符号链接读 IANA 名
    try:
        import os
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
