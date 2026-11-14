r"""配置写入的契约测试 —— 覆盖「所有调用方都在用的那种写法」。

## 为什么需要这个文件

`ethan/core/config.py` 是全局基础设施：**50 处调用点依赖它的语义**。
一旦它的行为变了，受影响的是模型管理、内核切换、语音后端、provider 配置、
渠道设置、fast-rules、api-keys、MCP 配置……全都会静默失效——
接口返回 `{"ok": true}` 但磁盘上什么都没写。

这种 bug 编译期、类型检查、单测（如果只测函数本身）都发现不了。
**必须验证「写完 → 读盘」这个端到端行为。**

历史上已经踩过一次：修并发时把 diff 基线设成内存单例，导致 50 处写入全部失效，
用户报「模型删不掉、加不上」才发现。

## 契约（三条）

1. `save_config(get_config() 改过的对象)` 必须落盘
2. 落盘内容必须与其他进程的改动合并（不整体覆盖）
3. 读回的内容必须与写进去的一致（含嵌套段）

本文件用「写入 → 重新从磁盘读」的方式验证，不 mock 存储层。
"""
from __future__ import annotations

import pytest
import yaml


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    """独立配置文件 + 重置所有模块级状态。"""
    import ethan.core.config as cfg_mod

    f = tmp_path / "config.yaml"
    f.write_text(
        yaml.dump({
            "models": [
                {"id": "m1", "provider": "p"},
                {"id": "m2", "provider": "p"},
            ],
            "defaults": {"model": "m1", "language": "zh"},
            "providers": {"p": {"api_key": "k", "type": "openai_compat"}},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", f)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "_config", None)
    monkeypatch.setattr(cfg_mod, "_last_saved_raw", None)
    return f


def _read(f) -> dict:
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


# ── 契约 1：get_config() 改完 save 必须落盘 ──────────────────


def test_mutation_then_save_persists(cfg_file):
    """**所有调用方都是这么写的** —— 必须能用。"""
    from ethan.core.config import get_config, save_config

    cfg = get_config()
    cfg.defaults.language = "en"
    cfg.models = cfg.models[:1]
    save_config(cfg)

    disk = _read(cfg_file)
    assert disk["defaults"]["language"] == "en"
    assert len(disk["models"]) == 1


def test_delete_works(cfg_file):
    from ethan.core.config import get_config, save_config

    cfg = get_config()
    cfg.models = [m for m in cfg.models if m.id != "m2"]
    save_config(cfg)
    assert [m["id"] for m in _read(cfg_file)["models"]] == ["m1"]


def test_add_works(cfg_file):
    from ethan.core.config import ModelEntry, get_config, save_config

    cfg = get_config()
    cfg.models.append(ModelEntry(id="m3", provider="p"))
    save_config(cfg)
    assert "m3" in [m["id"] for m in _read(cfg_file)["models"]]


# ── 契约 2：合并，不整体覆盖 ─────────────────────────────────


def test_does_not_clobber_concurrent_change(cfg_file):
    """另一个进程改了别的字段，本次保存不该抹掉它。"""
    from ethan.core.config import get_config, save_config

    base = get_config()          # 建基线（provider=p）

    # 另一进程把 provider 的 api_key 改了
    disk = _read(cfg_file)
    disk["providers"]["p"]["api_key"] = "NEW_KEY"
    cfg_file.write_text(yaml.dump(disk), encoding="utf-8")

    base.defaults.language = "en"   # A 只改了 language
    save_config(base)

    after = _read(cfg_file)
    assert after["providers"]["p"]["api_key"] == "NEW_KEY", "并发改动被抹掉了"
    assert after["defaults"]["language"] == "en", "本次改动没生效"


# ── 契约 3：嵌套段往返 ──────────────────────────────────────


def test_nested_section_roundtrip(cfg_file):
    """`defaults.kernel` 这类嵌套段必须能往返。

    pydantic 的 exclude_defaults 对嵌套模型是按「整个子对象」判定的，
    曾导致 kernel 段整段消失（切内核成功但配置不落盘）。
    """
    from ethan.core.config import get_config, save_config

    cfg = get_config()
    cfg.defaults.kernel.default = "dsh"
    cfg.defaults.kernel.task_rules = {"coding": "claude_code"}
    save_config(cfg)

    disk = _read(cfg_file)
    assert disk["defaults"]["kernel"]["default"] == "dsh"
    assert disk["defaults"]["kernel"]["task_rules"] == {"coding": "claude_code"}


def test_reload_after_save_sees_new_value(cfg_file):
    """写完重新加载（模拟服务重启）要看到新值。"""
    import ethan.core.config as cfg_mod

    cfg = cfg_mod.get_config()
    cfg.defaults.kernel.default = "pi"
    cfg_mod.save_config(cfg)

    cfg_mod._config = None
    cfg_mod._last_saved_raw = None
    fresh = cfg_mod.load_config()
    assert fresh.defaults.kernel.default == "pi"


# ── 幂等 ────────────────────────────────────────────────────


def test_repeated_save_is_idempotent(cfg_file):
    from ethan.core.config import get_config, save_config

    cfg = get_config()
    cfg.models = cfg.models[:1]
    save_config(cfg)
    once = _read(cfg_file)

    cfg2 = get_config()
    save_config(cfg2)   # 什么都没改
    assert _read(cfg_file)["models"] == once["models"]
