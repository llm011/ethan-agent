"""外部内核按会话模型同步与匹配的测试。

覆盖：
  1. 模型引用解析与候选匹配（精确、provider 前缀、点号/连字符等价、大小写、未命中返回 None）。
  2. ACP `config_options` 匹配与 `set_config_option` 调用（DSH 分组格式 + OpenCode 斜杠格式）。
  3. DSH `--patch` 注入优先使用本次会话模型（且不改全局 `defaults.model`），跳过 `anthropic` 类型。
  4. Pi / Claude Code / Codex 的模型发现、命令行透传与未命中回退。
  5. `KernelRunner` / `build_runner` 把聊天框请求模型透传至 `KernelRequest.model`。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


# ── 1. 模型解析与匹配 ─────────────────────────────────────────


def test_parse_model_ref_formats(monkeypatch):
    import ethan.core.config as cfg_mod
    from ethan.core.config import ModelEntry
    from ethan.kernel.model_sync import parse_model_ref

    cfg = cfg_mod.get_config()
    monkeypatch.setattr(
        cfg,
        "models",
        [ModelEntry(id="deepseek-v4.1-flash", provider="cliproxy", alias=["flash"])],
    )

    assert parse_model_ref("") is None
    assert parse_model_ref("   ") is None

    r1 = parse_model_ref("flash")
    assert r1 is not None and r1.provider == "cliproxy" and r1.model_id == "deepseek-v4.1-flash"

    r2 = parse_model_ref("yuntoken/claude-sonnet-4.6")
    assert r2 is not None and r2.provider == "yuntoken" and r2.model_id == "claude-sonnet-4.6"

    r3 = parse_model_ref("gpt-5.4")
    assert r3 is not None and r3.provider == "" and r3.model_id == "gpt-5.4"


def test_match_model_candidate_tiers():
    from ethan.kernel.model_sync import ModelCandidate, ModelRef, match_model_candidate

    cands = [
        ModelCandidate(value="cliproxy/claude-sonnet-4.6", provider="cliproxy", model_id="claude-sonnet-4.6"),
        ModelCandidate(value="yuntoken/claude-sonnet-4.6", provider="yuntoken", model_id="claude-sonnet-4.6"),
        ModelCandidate(value="buddy/claude-opus-4-6", provider="buddy", model_id="claude-opus-4-6"),
        ModelCandidate(value='["deepseek-official","deepseek-flash"]', provider="deepseek-official", model_id="deepseek-flash", name="DeepSeek-V4.1-Flash"),
    ]

    # 指定 provider 时精确命中对应 provider
    m1 = match_model_candidate(ModelRef("yuntoken/claude-sonnet-4.6", "yuntoken", "claude-sonnet-4.6"), cands)
    assert m1 is not None and m1.value == "yuntoken/claude-sonnet-4.6"

    # 点号/连字符等价（4.6 ↔ 4-6）
    m2 = match_model_candidate(ModelRef("claude-opus-4.6", "", "claude-opus-4.6"), cands)
    assert m2 is not None and m2.value == "buddy/claude-opus-4-6"

    # 忽略大小写匹配展示名
    m3 = match_model_candidate(ModelRef("deepseek-v4.1-flash", "", "deepseek-v4.1-flash"), cands)
    assert m3 is not None and m3.value == '["deepseek-official","deepseek-flash"]'

    # 未命中返回 None，绝不乱匹配
    assert match_model_candidate(ModelRef("nonexistent-model-99", "", "nonexistent-model-99"), cands) is None


# ── 2. ACP config_options 匹配与 set_config_option ─────────────


def test_match_acp_model_option_dsh_groups_and_opencode():
    from acp.schema import (
        SessionConfigOptionSelect,
        SessionConfigSelectGroup,
        SessionConfigSelectOption,
    )
    from ethan.kernel.model_sync import match_acp_model_option

    dsh_opts = [
        SessionConfigOptionSelect(
            id="model",
            name="Model",
            category="model",
            type="select",
            currentValue='["deepseek-official","deepseek-v4-flash"]',
            options=[
                SessionConfigSelectGroup(
                    group="deepseek-official",
                    name="DeepSeek",
                    options=[
                        SessionConfigSelectOption(
                            value='["deepseek-official","deepseek-v4-flash"]',
                            name="deepseek-v4-flash",
                        ),
                        SessionConfigSelectOption(
                            value='["deepseek-official","deepseek-v4-pro"]',
                            name="DeepSeek-V4-Pro",
                        ),
                    ],
                ),
                SessionConfigSelectGroup(
                    group="ethan",
                    name="ethan",
                    options=[
                        SessionConfigSelectOption(
                            value='["ethan","deepseek-v4-pro"]',
                            name="deepseek-v4-pro",
                        ),
                    ],
                ),
            ],
        )
    ]

    # 没有 preferred_group 时选原生
    m_native = match_acp_model_option("deepseek-v4-pro", dsh_opts)
    assert m_native == ("model", '["deepseek-official","deepseek-v4-pro"]', '["deepseek-official","deepseek-v4-flash"]')

    # DSH 注入了 ethan patch 时优先用 ethan 路由（携带有效 API Key）
    m_ethan = match_acp_model_option("deepseek-v4-pro", dsh_opts, preferred_group="ethan")
    assert m_ethan == ("model", '["ethan","deepseek-v4-pro"]', '["deepseek-official","deepseek-v4-flash"]')

    # OpenCode 扁平格式
    oc_opts = [
        SessionConfigOptionSelect(
            id="model",
            name="Model",
            category="model",
            type="select",
            currentValue="yuntoken/claude-sonnet-5",
            options=[
                SessionConfigSelectOption(value="cliproxy/claude-opus-4.6", name="cliproxy/claude-opus-4.6"),
                SessionConfigSelectOption(value="yuntoken/claude-sonnet-5", name="yuntoken/claude-sonnet-5"),
            ],
        )
    ]
    assert match_acp_model_option("claude-opus-4.6", oc_opts) == (
        "model",
        "cliproxy/claude-opus-4.6",
        "yuntoken/claude-sonnet-5",
    )
    assert match_acp_model_option("unknown-model", oc_opts) is None


def test_acp_apply_session_model_calls_set_config_option():
    from acp.schema import SessionConfigOptionSelect, SessionConfigSelectOption
    from ethan.kernel.acp_client_kernel import OpenCodeAcpKernel
    from ethan.kernel.runtime import KernelRequest

    calls: list[tuple[str, str, str]] = []

    class _FakeConn:
        async def set_config_option(self, *, config_id: str, session_id: str, value: str):
            calls.append((config_id, session_id, value))

    sess = SimpleNamespace(
        session_id="ses_1",
        config_options=[
            SessionConfigOptionSelect(
                id="model",
                name="Model",
                category="model",
                type="select",
                currentValue="yuntoken/claude-sonnet-5",
                options=[
                    SessionConfigSelectOption(value="cliproxy/claude-opus-4.6", name="cliproxy/claude-opus-4.6"),
                    SessionConfigSelectOption(value="yuntoken/claude-sonnet-5", name="yuntoken/claude-sonnet-5"),
                ],
            )
        ],
    )

    k = OpenCodeAcpKernel()
    req = KernelRequest(model="claude-opus-4.6")
    asyncio.run(k._apply_session_model(_FakeConn(), sess, req))
    assert calls == [("model", "ses_1", "cliproxy/claude-opus-4.6")]
    assert req.kernel_model == "cliproxy/claude-opus-4.6"

    # 若当前已经是目标模型，不重复调 set_config_option
    calls.clear()
    req2 = KernelRequest(model="claude-sonnet-5")
    asyncio.run(k._apply_session_model(_FakeConn(), sess, req2))
    assert calls == []
    assert req2.kernel_model == "yuntoken/claude-sonnet-5"

    # 未命中模型时不调用 set_config_option
    req3 = KernelRequest(model="no-such-model")
    asyncio.run(k._apply_session_model(_FakeConn(), sess, req3))
    assert calls == []
    assert req3.kernel_model == ""


# ── 3. DSH provider patch 按会话生效、不改全局 ─────────────────


def test_dsh_build_provider_patch_uses_session_model_without_mutating_global(monkeypatch):
    import os
    import yaml
    import ethan.core.config as cfg_mod
    from ethan.core.config import ModelEntry, ProviderConfig
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    cfg = cfg_mod.get_config()
    monkeypatch.setattr(cfg.defaults, "model", "deepseek/deepseek-chat")
    monkeypatch.setattr(
        cfg,
        "models",
        [
            ModelEntry(id="deepseek-chat", provider="deepseek"),
            ModelEntry(id="gpt-5.4", provider="cliproxy"),
            ModelEntry(id="claude-opus-4.6", provider="anthropic_direct"),
        ],
    )
    monkeypatch.setattr(
        cfg,
        "providers",
        {
            "deepseek": ProviderConfig(api_key="sk-ds", base_url="https://api.deepseek.com/v1", type="openai_compat"),
            "cliproxy": ProviderConfig(api_key="sk-cp", base_url="http://127.0.0.1:8317/v1", type="openai_compat"),
            "anthropic_direct": ProviderConfig(api_key="sk-ant", base_url="https://api.anthropic.com", type="anthropic"),
        },
    )

    k = DshAcpKernel()
    # 传入裸模型名 "gpt-5.4" → 命中 cliproxy/gpt-5.4，且全局 defaults.model 不变
    path, env = k._build_provider_patch(model="gpt-5.4")
    try:
        assert path
        assert env == {"ETHAN_ACP_PROVIDER_KEY": "sk-cp"}
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        assert data[0]["config"]["providers"]["ethan"]["models"] == [{"id": "gpt-5.4"}]
        assert data[1]["config"]["model"] == "gpt-5.4"
        assert cfg.defaults.model == "deepseek/deepseek-chat"
    finally:
        if path:
            os.unlink(path)

    # anthropic 类型不走 openai-completions patch，回退到 defaults.model 以保留 DSH 可用凭证
    path2, env2 = k._build_provider_patch(model="claude-opus-4.6")
    try:
        assert path2
        assert env2 == {"ETHAN_ACP_PROVIDER_KEY": "sk-ds"}
        data2 = yaml.safe_load(Path(path2).read_text(encoding="utf-8"))
        assert data2[1]["config"]["model"] == "deepseek-chat"
    finally:
        if path2:
            os.unlink(path2)


# ── 4. Pi / Claude Code / Codex 模型匹配与 CLI 参数 ─────────────


def test_pi_kernel_passes_matched_model_only_when_found(monkeypatch):
    from ethan.kernel import model_sync
    from ethan.kernel.pi_kernel import PiKernel
    from ethan.kernel.runtime import KernelRequest

    model_sync.clear_model_sync_caches()

    async def fake_list_pi_models(binary: str = "pi"):
        return [
            ("buddy", "claude-sonnet-4-6"),
            ("deepseek", "deepseek-v4-pro"),
        ]

    monkeypatch.setattr(model_sync, "list_pi_models", fake_list_pi_models)

    recorded_cmds: list[list[str]] = []

    class _FakeProc:
        returncode = 0
        stdout = None
        stderr = None

        def __init__(self):
            self._lines = [b'{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"ok"}}\n']

        async def wait(self):
            return 0

    class _FakeStream:
        def __init__(self, lines):
            self._lines = list(lines)

        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

        async def read(self):
            return b"".join(self._lines)

    async def fake_exec(*cmd, **kwargs):
        recorded_cmds.append(list(cmd))
        p = _FakeProc()
        p.stdout = _FakeStream([b'{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"ok"}}\n'])
        p.stderr = _FakeStream([])
        return p

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    k = PiKernel()
    q: asyncio.Queue = asyncio.Queue()

    # 命中点号/连字符等价模型
    req1 = KernelRequest(model="claude-sonnet-4.6")
    asyncio.run(k._consume("hi", req1, q))
    assert "--model" in recorded_cmds[-1]
    idx = recorded_cmds[-1].index("--model")
    assert recorded_cmds[-1][idx + 1] == "buddy/claude-sonnet-4-6"
    assert req1.kernel_model == "buddy/claude-sonnet-4-6"

    # 未命中时不传 --model
    req2 = KernelRequest(model="unknown-xyz")
    asyncio.run(k._consume("hi", req2, q))
    assert "--model" not in recorded_cmds[-1]
    assert req2.kernel_model == ""


def test_resolve_claude_model(tmp_path: Path):
    from ethan.kernel.model_sync import resolve_claude_model

    cdir = tmp_path / ".claude"
    cdir.mkdir()
    (cdir / "settings.json").write_text(
        json.dumps(
            {
                "model": "gemini-4-hydrogen",
                "env": {
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "gemini-4-argon",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-5-5",
                },
            }
        ),
        encoding="utf-8",
    )

    assert asyncio.run(resolve_claude_model("gemini-4-hydrogen", claude_dir=cdir, probe_remote=False)) == "gemini-4-hydrogen"
    assert asyncio.run(resolve_claude_model("gemini-4-argon", claude_dir=cdir, probe_remote=False)) == "gemini-4-argon"
    assert asyncio.run(resolve_claude_model("sonnet", claude_dir=cdir, probe_remote=False)) == "sonnet"
    assert asyncio.run(resolve_claude_model("claude-opus-4-6", claude_dir=cdir, probe_remote=False)) == "claude-opus-4-6"
    assert asyncio.run(resolve_claude_model("gpt-5.4", claude_dir=cdir, probe_remote=False)) is None


def test_resolve_codex_model(tmp_path: Path):
    from ethan.kernel.model_sync import resolve_codex_model

    cdir = tmp_path / ".codex"
    cdir.mkdir()
    (cdir / "config.toml").write_text(
        'model = "deepseek-v4.1-flash"\n'
        'model_provider = "buddy"\n'
        '[notice.model_migrations]\n'
        '"gpt-5.2-codex" = "gpt-5.4"\n',
        encoding="utf-8",
    )

    assert asyncio.run(resolve_codex_model("deepseek-v4.1-flash", codex_home=cdir, probe_remote=False)) == "deepseek-v4.1-flash"
    assert asyncio.run(resolve_codex_model("gpt-5.4", codex_home=cdir, probe_remote=False)) == "gpt-5.4"
    assert asyncio.run(resolve_codex_model("claude-opus-4.6", codex_home=cdir, probe_remote=False)) is None

    # 官方 OpenAI provider 支持 gpt-*/codex-* 前缀
    cdir2 = tmp_path / ".codex2"
    cdir2.mkdir()
    (cdir2 / "config.toml").write_text('model = "o3"\n', encoding="utf-8")
    assert asyncio.run(resolve_codex_model("gpt-5.5", codex_home=cdir2, probe_remote=False)) == "gpt-5.5"


def test_claude_kernel_passes_model_to_delegate_only_when_matched(monkeypatch):
    import ethan.acp as acp_mod
    from ethan.acp.models import ACPResult
    from ethan.kernel.claude_kernel import ClaudeCodeKernel
    from ethan.kernel.runtime import KernelRequest

    seen_kwargs: list[dict] = []

    async def fake_delegate(**kwargs):
        seen_kwargs.append(kwargs)
        return ACPResult(success=True, output="ok", agent="claude")

    monkeypatch.setattr(acp_mod, "delegate", fake_delegate)
    monkeypatch.setattr(ClaudeCodeKernel, "available", lambda self: (True, ""))
    monkeypatch.setattr(
        "ethan.kernel.model_sync.resolve_claude_model",
        lambda raw, **kw: asyncio.sleep(0, result="claude-opus-4-6" if "opus" in raw else None),
    )

    async def _run_with(model_str: str):
        req = KernelRequest(messages=[SimpleNamespace(role="user", content="hi", images=[])], model=model_str)
        out = [e async for e in ClaudeCodeKernel().run(req)]
        return req, out

    req_hit, _ = asyncio.run(_run_with("claude-opus-4.6"))
    assert seen_kwargs[-1].get("model") == "claude-opus-4-6"
    assert req_hit.kernel_model == "claude-opus-4-6"

    req_miss, _ = asyncio.run(_run_with("gpt-5.4"))
    assert "model" not in seen_kwargs[-1]
    assert req_miss.kernel_model == ""


# ── 5. KernelRunner / build_runner 透传 requested_model ────────


def test_build_runner_forwards_requested_model_to_kernel_request(monkeypatch):
    import ethan.core.config as cfg_mod
    from ethan.kernel.dispatch import build_runner
    from ethan.kernel.runtime import KernelKind, KernelRuntime, get_kernel_registry, reset_kernel_registry

    captured: list[str] = []

    class _ProbeKernel(KernelRuntime):
        kind = KernelKind.OPENCODE
        display_name = "OpenCode"

        def available(self):
            return True, ""

        async def run(self, request, context=None):
            captured.append(request.model)
            request.kernel_model = "cliproxy/claude-opus-4.6"
            yield "done"

    reset_kernel_registry()
    reg = get_kernel_registry()
    reg.register(_ProbeKernel())

    cfg = cfg_mod.get_config()
    monkeypatch.setattr(cfg.defaults, "model", "deepseek-chat")
    monkeypatch.setattr(cfg.defaults.kernel, "default", "opencode")

    stub = SimpleNamespace(
        model="claude-opus-4.6",
        session_id="s_1",
        runtime_context="",
        _channel="web",
        _user_id="u_1",
        _mode="",
        _registry=None,
        _skills=None,
        usage=SimpleNamespace(input_tokens=0, output_tokens=0, cache_tokens=0),
    )
    runner = build_runner(stub, requested_model="cliproxy/claude-opus-4.6")

    async def _collect():
        return [e async for e in runner.stream_chat([])]

    try:
        out = asyncio.run(_collect())
    finally:
        reset_kernel_registry()

    assert out == ["done"]
    assert captured == ["cliproxy/claude-opus-4.6"]
    assert runner.kernel_model == "cliproxy/claude-opus-4.6"
    assert runner.real_model == "claude-opus-4.6"
    # 全局 defaults.model 未被修改
    assert cfg.defaults.model == "deepseek-chat"


def test_codex_and_claude_runners_pass_cli_model_flag(monkeypatch):
    import shutil
    from ethan.acp.agent_claude import _run_claude_code
    from ethan.acp.agent_codex import _run_codex

    cmds: list[list[str]] = []

    class _Stream:
        async def readline(self):
            return b""

    class _Proc:
        returncode = 0
        stdout = _Stream()

        async def wait(self):
            return 0

    async def fake_exec(*cmd, **kwargs):
        cmds.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setenv("ETHAN_CODEX_NO_PROVIDER_OVERRIDE", "1")

    asyncio.run(_run_claude_code("hello", cwd="/tmp", model="claude-opus-4-6"))
    assert "--model" in cmds[-1]
    assert cmds[-1][cmds[-1].index("--model") + 1] == "claude-opus-4-6"

    asyncio.run(_run_codex("hello", cwd="/tmp", model="gpt-5.4"))
    assert "-m" in cmds[-1]
    assert cmds[-1][cmds[-1].index("-m") + 1] == "gpt-5.4"
