"""飞书 lark_oapi client 构建。"""
from __future__ import annotations


def _lark_client():
    """构建 lark_oapi client，未配置返回 None。"""
    import lark_oapi as lark
    from ethan.core.config import get_config
    lark_cfg = getattr(get_config(), "lark", None)
    if not lark_cfg or not lark_cfg.app_id:
        return None
    return (
        lark.Client.builder()
        .app_id(lark_cfg.app_id)
        .app_secret(lark_cfg.app_secret)
        .build()
    )
