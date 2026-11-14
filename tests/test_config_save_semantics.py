r"""`save_config` 的语义回归测试 —— 覆盖「改完再存」这种最常见用法。

## 背景（严重回归）

修配置并发时，我让 `save_config` 拿 `_config` 单例做 diff 基线。但绝大多数
既有调用方的写法是：

    cfg = get_config()
    cfg.models = [...]        # 同时也改了 _config 单例
    save_config(cfg)          # 基线 == 待写对象 → 变更集恒为空 → 什么都没写

后果是**系统性功能失效**：模型删不掉/加不上、切内核不落盘、语音后端设了没反应……
54 处调用点全部受影响。

## 正确做法

基线必须是「上一次成功落盘的内容快照」（`_last_saved_raw`），
而不是「当前内存对象」。这样：
  · 「改完再存」能正确算出变更（本次改动确实与上次落盘不同）
  · 并发方的其它改动仍被保住（不在 delta 里的字段用盘上的值）

本文件锁死这两条，防止再次退化。
"""
from __future__ import annotations

import pytest
import yaml


@pytest.fixture
def isolated_cfg(tmp_path, monkeypatch):
    """把配置文件指到临时目录，并重置单例与基线。"""
    import ethan.core.config as cfg_mod

    f = tmp_path / "config.yaml"
    f.write_text(
        yaml.dump({
            "models": [
                {"id": "m1", "provider": "p"},
                {"id": "m2", "provider": "p"},
                {"id": "m3", "provider": "p"},
            ],
            "defaults": {"model": "m1"},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", f)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "_config", None)
    monkeypatch.setattr(cfg_mod, "_last_saved_raw", None)
    return f


def _disk_models(f) -> list:
    return yaml.safe_load(f.read_text())["models"]


def test_delete_persists(isolated_cfg):
    """最常见的写法：get_config() 改完直接 save —— 必须落盘。"""
    from ethan.core.config import get_config, save_config

    cfg = get_config()
    cfg.models = [m for m in cfg.models if m.id != "m2"]
    save_config(cfg)

    assert len(_disk_models(isolated_cfg)) == 2, "删除没落盘"


def test_add_persists(isolated_cfg):
    from ethan.core.config import ModelEntry, get_config, save_config

    cfg = get_config()
    cfg.models.append(ModelEntry(id="m4", provider="p"))
    save_config(cfg)

    ids = [m["id"] for m in _disk_models(isolated_cfg)]
    assert "m4" in ids, "新增没落盘"


def test_modify_persists(isolated_cfg):
    from ethan.core.config import get_config, save_config

    cfg = get_config()
    for m in cfg.models:
        if m.id == "m1":
            m.description = "changed"
    save_config(cfg)

    item = next(m for m in _disk_models(isolated_cfg) if m["id"] == "m1")
    assert item.get("description") == "changed", "修改没落盘"


def test_repeated_saves_are_idempotent(isolated_cfg):
    """连续保存两次不该丢东西（第二次的 delta 应为空但内容不变）。"""
    from ethan.core.config import get_config, save_config

    cfg = get_config()
    cfg.models = cfg.models[:-1]
    save_config(cfg)
    after_first = len(_disk_models(isolated_cfg))

    cfg2 = get_config()
    save_config(cfg2)  # 什么都没改
    assert len(_disk_models(isolated_cfg)) == after_first


def test_concurrent_change_preserved(isolated_cfg):
    """A 基于过期快照保存，不该抹掉 B 期间的改动。"""
    from ethan.core.config import get_config, save_config

    # B 在盘上加了 m5
    data = yaml.safe_load(isolated_cfg.read_text())
    data["models"].append({"id": "m5", "provider": "p"})
    isolated_cfg.write_text(yaml.dump(data), encoding="utf-8")

    # A 用当前内存（只有 m1/m2/m3）删掉 m2 —— 基线里有 m1/m2/m3，
    # m5 不在基线里，所以 delta 不含它，落盘时应保住
    cfg = get_config()
    cfg.models = [m for m in cfg.models if m.id != "m2"]
    save_config(cfg)

    ids = [m["id"] for m in _disk_models(isolated_cfg)]
    assert "m5" in ids, "并发方新增的 m5 被抹掉了"
    assert "m2" not in ids, "本次删除没生效"
