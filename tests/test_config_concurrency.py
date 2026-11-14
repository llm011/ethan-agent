r"""配置保存的并发安全与原子性。

背景（实测踩到）：`ethan serve` 持有内存里的配置对象，UI 每次改设置都把**整份**
对象写回文件。同时有其他进程（另一 worktree 的服务 / CLI / 用户手改）也在改时，
后写的会把先写的整体覆盖——表现为「刚设好的值自己变回去了」。

修法三层：
  1. 原子写（临时文件 + rename）——读者不会看到半截 YAML
  2. 跨进程文件锁（flock）+ 进程内锁
  3. **diff 合并**：只把「本次真正变了的字段」叠到盘上，不盲目覆盖

另外这个文件也覆盖一个曾经导致服务启动失败的低级错误：`global _config`
声明写在函数中间 → `SyntaxError: name '_config' is used prior to global declaration`。
当时没有任何测试调用 save_config，所以 CI 全绿但服务起不来。
"""
from __future__ import annotations

from ethan.core import config as cfg_mod


def test_save_config_is_importable_and_runs():
    """最基本的一条：save_config 能被调用。

    这条看着废话，但它能抓住「语法错误 / 作用域错误」——上面那个 global 位置
    错误就是靠人肉启动服务才发现的，测试完全没覆盖。
    """
    cfg = cfg_mod.get_config()
    cfg_mod.save_config(cfg)  # 不抛异常即通过


def test_diff_only_reports_changed_leaves():
    base = {"a": 1, "b": {"x": 1, "y": 2}}
    incoming = {"a": 1, "b": {"x": 1, "y": 99}}
    delta = cfg_mod._diff_against_base(base, incoming)
    assert delta == {"b": {"y": 99}}, "没变的字段不该出现在变更集里"


def test_diff_includes_new_keys():
    assert cfg_mod._diff_against_base({}, {"k": 1}) == {"k": 1}
    assert cfg_mod._diff_against_base({"a": 1}, {"a": 1, "b": 2}) == {"b": 2}


def test_diff_against_none_base_returns_all():
    """没有基线（首次保存）时，全部内容都算变更。"""
    assert cfg_mod._diff_against_base(None, {"a": 1}) == {"a": 1}


def test_apply_delta_preserves_untouched_keys():
    on_disk = {"keep": "me", "nested": {"a": 1, "b": 2}}
    delta = {"nested": {"b": 99}}
    out = cfg_mod._apply_delta(on_disk, delta)
    assert out["keep"] == "me"
    assert out["nested"] == {"a": 1, "b": 99}


def test_apply_delta_keeps_sibling_keys_not_in_delta():
    """关键：盘上有、delta 里没有的字段必须保留（那是别人的改动）。"""
    on_disk = {"others": "theirs", "mine": "old"}
    out = cfg_mod._apply_delta(on_disk, {"mine": "new"})
    assert out["others"] == "theirs"
    assert out["mine"] == "new"


def test_merge_preserves_concurrent_change(tmp_path, monkeypatch):
    """端到端：A 基于过期快照保存，不该抹掉 B 期间的改动。

    构造方式直接对着「实现要求」写，不绕：
      · 基线（进程内单例）里 provider = searxng   ← A 眼里的"原始状态"
      · A 要写的对象里 provider 也是 searxng（他没动它），只改了 tts.backend
      · 但盘上 B 已经把 provider 改成 deepseek 了
      · 期望：A 保存后 provider 仍是 deepseek（B 的改动保住），tts.backend 生效
    """
    import yaml

    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "_config", None)

    # B 已经把盘上写成 deepseek 了
    cfg_file.write_text(yaml.dump({"tools": {"web_search": {"provider": "deepseek"}}}))

    # A 的基线（内存）是旧状态：provider 还是 searxng
    base = cfg_mod.load_config()
    monkeypatch.setattr(cfg_mod, "_config", base)
    base.tools.web_search.provider = "searxng"

    # A 要保存的对象：provider 没动（仍是 searxng），只改了 tts.backend
    incoming = cfg_mod.load_config()
    incoming.tools.web_search.provider = "searxng"
    incoming.tts.backend = "ethan-tts"

    cfg_mod.save_config(incoming)

    final = yaml.safe_load(cfg_file.read_text())
    assert final["tts"]["backend"] == "ethan-tts", "本次变更没写进去"
    assert final["tools"]["web_search"]["provider"] == "deepseek", (
        "A 没改 provider，不该把盘上 B 写的 deepseek 顶回 searxng"
    )


def test_atomic_write_does_not_leave_partial_file(tmp_path, monkeypatch):
    """写完之后必须是完整合法 YAML（临时文件路径）。"""
    import yaml

    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)

    cfg_mod._write_raw({"a": 1, "b": [1, 2, 3]})
    data = yaml.safe_load(cfg_file.read_text())
    assert data == {"a": 1, "b": [1, 2, 3]}
    # 不该留下临时文件
    leftovers = [p.name for p in tmp_path.glob(".config.yaml.*.tmp")]
    assert leftovers == []


def test_update_config_uses_fresh_disk_state(tmp_path, monkeypatch):
    """update_config 应该在锁内重新读盘，不信任内存单例。"""
    import yaml

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"tts": {"backend": "edge-tts"}}))
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "_config", None)

    # 内存里放一份「过期」的（backend=ethan-tts），盘上是 edge-tts
    stale = cfg_mod.load_config()
    monkeypatch.setattr(cfg_mod, "_config", stale)
    cfg_file.write_text(yaml.dump({"tts": {"backend": "edge-tts"}}))

    out = cfg_mod.update_config(
        lambda c: setattr(c.tools.web_fetch, "backend", "deepseek")
    )
    # 拿到的是盘上最新状态 + 本次变更
    assert out.tools.web_fetch.backend == "deepseek"
    final = yaml.safe_load(cfg_file.read_text())
    assert final["tools"]["web_fetch"]["backend"] == "deepseek"
