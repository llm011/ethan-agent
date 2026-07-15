"""Tests for _is_local — auto_consent 安全门禁。

_is_local 决定 auto_consent 是否生效（等价于放开 RCE），必须严格限定来源：
回环 + 三段 RFC1918 私有网段，其他一律拦截。
"""
from __future__ import annotations

from unittest.mock import MagicMock

from ethan.interface.routers.chat import _is_local


def _request_with_host(host: str):
    req = MagicMock()
    req.client = MagicMock(host=host)
    return req


def test_loopback_ipv4():
    assert _is_local(_request_with_host("127.0.0.1")) is True


def test_loopback_ipv6():
    assert _is_local(_request_with_host("::1")) is True


def test_loopback_localhost():
    assert _is_local(_request_with_host("localhost")) is True


def test_docker_bridge():
    """docker 网桥 IP（172.17.0.1）必须通过——这是修复的核心动机。"""
    assert _is_local(_request_with_host("172.17.0.1")) is True


def test_rfc1918_10():
    assert _is_local(_request_with_host("10.0.0.1")) is True


def test_rfc1918_192():
    assert _is_local(_request_with_host("192.168.1.1")) is True


def test_rfc1918_172_16():
    """172.16.0.0/12 的边界。"""
    assert _is_local(_request_with_host("172.16.0.1")) is True
    assert _is_local(_request_with_host("172.31.255.255")) is True


def test_rfc1918_172_32_outside():
    """172.32.x 不在私有段内。"""
    assert _is_local(_request_with_host("172.32.0.1")) is False


def test_public_google_dns():
    assert _is_local(_request_with_host("8.8.8.8")) is False


def test_public_cloudflare():
    assert _is_local(_request_with_host("1.1.1.1")) is False


def test_cgnat_blocked():
    """100.64/10 (CGNAT) 不是 RFC1918，必须拦截。"""
    assert _is_local(_request_with_host("100.64.0.1")) is False


def test_link_local_blocked():
    """169.254/16 (链路本地，含云 metadata) 必须拦截。"""
    assert _is_local(_request_with_host("169.254.169.254")) is False


def test_client_none():
    """client 为 None（异常情况）按非本地处理。"""
    req = MagicMock()
    req.client = None
    assert _is_local(req) is False


def test_non_ip_string():
    """非 IP 字符串拦截。"""
    assert _is_local(_request_with_host("not-an-ip")) is False
    assert _is_local(_request_with_host("foo.example.com")) is False
