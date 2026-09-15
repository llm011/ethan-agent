# -*- coding: utf-8 -*-
"""config.yaml 的 server.host / server.port 支持（端到端优先级）。

优先级约定：显式 CLI 参数 > config.yaml > 内置默认（0.0.0.0:8900）。
环境变量 ETHAN_SERVER_HOST / ETHAN_SERVER_PORT 按既有 ETHAN_* 惯例**无条件**
覆盖 config.yaml——因为 _default_config() 首次就会把 0.0.0.0:8900 写进文件，
若做成「config 优先」，docker/脚本设了环境变量也永远不生效。
"""
from __future__ import annotations

import textwrap

import pytest

from ethan.core import config as config_mod
from ethan.core.config import ServerConfig, get_config


@pytest.fixture()
def cfg_file(tmp_path, monkeypatch):
    """把 CONFIG_FILE 指到临时目录并清空配置缓存，避免污染真实 ~/.ethan。

    注意：不能在这里预调 reload_config()——那会把一份「文件还没写」的配置
    塞进缓存，测试后面写文件、get_config() 拿到的还是旧缓存。
    这里只清缓存，让测试内的 get_config() 自己去读临时文件。
    """
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config_mod, "CONFIG_FILE", path)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_config", None)
    yield path
    monkeypatch.setattr(config_mod, "_config", None)


def _write(path, body: str) -> None:
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def test_server_config_defaults():
    """默认监听 0.0.0.0:8900，与旧硬编码值一致（不能悄悄改默认行为）。"""
    srv = ServerConfig()
    assert srv.host == "0.0.0.0"
    assert srv.port == 8900


def test_config_yaml_port_takes_effect(cfg_file, monkeypatch):
    """config.yaml 里写 server.port → get_config().server.port 读到该值。"""
    monkeypatch.delenv("ETHAN_SERVER_PORT", raising=False)
    monkeypatch.delenv("ETHAN_SERVER_HOST", raising=False)
    _write(
        cfg_file,
        """
        server:
          host: 127.0.0.1
          port: 8981
        """,
    )
    cfg = get_config()
    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 8981


def test_env_overrides_config_yaml(cfg_file, monkeypatch):
    """环境变量赢过 config.yaml（docker/脚本依赖这条）。"""
    _write(
        cfg_file,
        """
        server:
          host: 127.0.0.1
          port: 8981
        """,
    )
    monkeypatch.setenv("ETHAN_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("ETHAN_SERVER_PORT", "8999")
    cfg = get_config()
    assert cfg.server.host == "0.0.0.0"
    assert cfg.server.port == 8999


def test_env_port_wins_even_when_config_has_default_written(cfg_file, monkeypatch):
    """回归点：_default_config() 会把 8900 落进文件，env 仍必须覆盖。

    早期实现是「config 里显式写了就不让 env 覆盖」，结果 setup 生成的
    config.yaml 永远含 server.port: 8900，ETHAN_SERVER_PORT 形同虚设。
    """
    _write(
        cfg_file,
        """
        server:
          host: 0.0.0.0
          port: 8900
        """,
    )
    monkeypatch.setenv("ETHAN_SERVER_PORT", "9123")
    assert get_config().server.port == 9123


def test_invalid_env_port_falls_back_to_config(cfg_file, monkeypatch):
    """非法端口值忽略（不抛异常、不把服务搞挂），退回 config 里的值。"""
    _write(
        cfg_file,
        """
        server:
          port: 8981
        """,
    )
    monkeypatch.setenv("ETHAN_SERVER_PORT", "not-a-number")
    assert get_config().server.port == 8981


def test_default_config_includes_server_section(cfg_file, monkeypatch):
    """setup 生成的 config 默认就带 server 段，用户知道去哪改端口。"""
    monkeypatch.delenv("ETHAN_SERVER_HOST", raising=False)
    monkeypatch.delenv("ETHAN_SERVER_PORT", raising=False)
    default = config_mod._default_config()
    assert default["server"]["host"] == "0.0.0.0"
    assert default["server"]["port"] == 8900


def test_explicit_cli_arg_beats_config(cfg_file, monkeypatch):
    """显式 --port 优先级最高，config 不该把它顶掉。"""
    from ethan.interface.cli import _server_bind_defaults

    _write(
        cfg_file,
        """
        server:
          host: 127.0.0.1
          port: 8981
        """,
    )
    assert _server_bind_defaults("1.2.3.4", 7000) == ("1.2.3.4", 7000)


def test_unspecified_cli_arg_follows_config(cfg_file, monkeypatch):
    """不传 --host/--port 时跟随 config（launchd plist 就是裸 serve）。"""
    from ethan.interface.cli import _server_bind_defaults

    monkeypatch.delenv("ETHAN_SERVER_HOST", raising=False)
    monkeypatch.delenv("ETHAN_SERVER_PORT", raising=False)
    _write(
        cfg_file,
        """
        server:
          host: 127.0.0.1
          port: 8981
        """,
    )
    assert _server_bind_defaults(None, None) == ("127.0.0.1", 8981)


def test_partial_cli_arg_mixes_with_config(cfg_file, monkeypatch):
    """只传了 --port，host 仍取 config，反之亦然。"""
    from ethan.interface.cli import _server_bind_defaults

    monkeypatch.delenv("ETHAN_SERVER_HOST", raising=False)
    monkeypatch.delenv("ETHAN_SERVER_PORT", raising=False)
    _write(
        cfg_file,
        """
        server:
          host: 127.0.0.1
          port: 8981
        """,
    )
    assert _server_bind_defaults(None, 7000) == ("127.0.0.1", 7000)
    assert _server_bind_defaults("1.2.3.4", None) == ("1.2.3.4", 8981)


def test_broken_config_still_yields_usable_bind(cfg_file, monkeypatch):
    """config 损坏时静默回退默认——绑定地址不该因为配置问题导致服务起不来。"""
    from ethan.interface.cli import _server_bind_defaults

    cfg_file.write_text("server: {port: [this is not valid", encoding="utf-8")
    host, port = _server_bind_defaults(None, None)
    assert host == "0.0.0.0"
    assert port == 8900
