r"""Ethan 工具通过 MCP 注入给外部内核的测试。

## 这个能力解决什么

用户原话：「我不希望只是连接一个外部内核去用三方 agent，我希望内核能连接进来
作为 ethan 的心脏来驱动它干活」。

换掉的是**大脑**（规划/推理），不该丢掉**手脚**（工具/技能）。所以把 Ethan 的
工具经 MCP 暴露给外部内核，让它用 Ethan 的搜索/知识库/文件能力干活。

## 三个必须锁住的点

1. **shell 永不暴露**——外部 agent 拿到 shell 等于拿到整台机器，而它的权限模型
   （`--approval-policy` / `--dangerously-skip-permissions`）与 Ethan 的 consent
   不同源，中间拦不住。
2. **不污染外部 agent 的配置**——`mcp_servers` 是 `new_session()` 的每次调用参数，
   不写入任何文件。实测验证：注入后 dsh 自带的 22 个工具全在。
3. **工具真的能被调用**——踩过三个坑：FastMCP 把 `**kwargs` 当必填字段、
   `structured_output` 要求返回结构化对象、返回裸 str 被当字符逐个解析。
"""
from __future__ import annotations

from ethan.kernel.tool_bridge import NEVER_EXPOSE, build_mcp_tools

# ── 暴露范围 ─────────────────────────────────────────────────


def test_shell_never_exposed():
    """最重要的一条。shell = 整台机器，绝不能交给外部 agent。"""
    names = {t.name for t in build_mcp_tools()}
    assert "shell" not in names


def test_self_modifying_tools_never_exposed():
    """改 Ethan 自身人格/配置的工具不暴露。

    外部 agent 误触的代价远高于收益（比如它"贴心地"把 lark.app_id 清空）。
    """
    names = {t.name for t in build_mcp_tools()}
    for dangerous in ("config_set", "profile_update", "procedure_write"):
        assert dangerous not in names, f"{dangerous} 不该暴露"


def test_memory_write_is_exposed():
    """memory_write **要**暴露，与 profile_update / procedure_write 区别对待。

    记忆是「对话产生的事实」，不是「Ethan 的自我定义」：用户在外部内核（DSH）
    里说「以后都叫我阿凌」，记不住才是 bug。写入怎么落库（证据等级、supersede）
    由 memory_write 内部的准入管道决定，外部内核无从指定。

    这条与上面那条是成对的：不许把 memory_write 又塞回 NEVER_EXPOSE。
    """
    names = {t.name for t in build_mcp_tools()}
    assert "memory_write" in names
    assert "memory_write" not in NEVER_EXPOSE


def test_secrets_tools_exposed():
    """密钥类工具**开放**（用户明确要求）。

    外部内核要真正干活常常需要 API key 去调第三方服务；不给就只能猜。
    风险由 Ethan 侧承担：这些工具本身有各自的 consent 与掩码逻辑。
    """
    names = {t.name for t in build_mcp_tools()}
    for t in ("get_secret", "list_secrets", "set_secret"):
        assert t in names, f"{t} 应该开放"


def test_file_write_exposed():
    """写文件必须开放，否则外部内核干不了活（只读等于废掉大半能力）。"""
    assert "file_write" in {t.name for t in build_mcp_tools()}


def test_readonly_mode_still_works():
    """保守模式可用：只暴露只读工具。"""
    names = {t.name for t in build_mcp_tools(share="readonly")}
    assert "web_search" in names
    assert "file_write" not in names


def test_all_mode_is_superset_of_readonly():
    ro = {t.name for t in build_mcp_tools(share="readonly")}
    all_ = {t.name for t in build_mcp_tools(share="all")}
    assert ro <= all_, "all 模式应该覆盖 readonly 的全部"


def test_never_expose_is_respected_in_all_modes():
    for share in ("readonly", "all"):
        names = {t.name for t in build_mcp_tools(share=share)}
        assert not (NEVER_EXPOSE & names - {"get_secret", "list_secrets", "set_secret"}), (
            f"share={share} 下 NEVER_EXPOSE 里的工具泄漏了"
        )


# ── 工具名前缀 ───────────────────────────────────────────────


def test_tool_schema_prefixes_names():
    """注入的工具名带 ethan_ 前缀，避免和外部 agent 自带的同名工具打架。"""
    from ethan.kernel.tool_bridge import _tool_schema

    tools = build_mcp_tools(share="readonly")
    tool = next(t for t in tools if t.name == "web_search")
    schema = _tool_schema(tool)
    assert schema["name"] == "ethan_web_search"
    # schema 是标准 JSON Schema，直接透传给 MCP 的 inputSchema
    assert schema["inputSchema"]["type"] == "object"
    assert "query" in schema["inputSchema"]["properties"]


# ── MCP server 声明 ─────────────────────────────────────────


def test_build_mcp_servers_uses_http_header_model(monkeypatch):
    """headers 必须是 HttpHeader 模型。

    传 (name, value) 元组会让 pydantic 校验失败，异常被兜住 → **静默不注入**，
    表现为「内核用的还是它自己的工具」，很难排查。实测踩到。
    """
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    servers = DshAcpKernel()._build_mcp_servers()
    assert servers, "应该构造出至少一个 MCP server"
    for h in servers[0].headers:
        # 元组没有 .name
        assert hasattr(h, "name") and hasattr(h, "value")


def test_build_mcp_servers_respects_off(monkeypatch):
    """share_tools="off" 时不注入（外部内核只用它自己的工具）。"""
    import ethan.core.config as cfg_mod

    cfg = cfg_mod.get_config()
    monkeypatch.setattr(cfg.defaults.kernel, "share_tools", "off", raising=False)
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    assert DshAcpKernel()._build_mcp_servers() == []


def test_mcp_server_url_points_at_kernel_tools():
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    servers = DshAcpKernel()._build_mcp_servers()
    if servers:
        assert servers[0].url.endswith("/kernel-tools/")


# ── 端点注册 ─────────────────────────────────────────────────


def test_endpoint_registers_all_tools_with_valid_schema():
    """58 个工具都要注册成功，且 schema 合法。

    这里同时回归三个踩过的坑：
      · FastMCP 把 **kwargs 当必填字段 → 调用必失败
      · structured_output 要求返回结构化对象 → 返回 str 必失败
      · 返回裸 str 会被当字符逐块解析 → 上万条校验错误
    """
    from ethan.interface.routers import kernel_mcp

    kernel_mcp._registered = False
    kernel_mcp._register_tools()

    tools = kernel_mcp.kernel_mcp._tool_manager._tools
    assert len(tools) >= 50, f"注册的工具太少：{len(tools)}"

    for name, tool in tools.items():
        assert name.startswith("ethan_")
        assert tool.parameters.get("type") == "object", f"{name} 的 schema 不是 object"


# ── Claude Code 的 MCP 注入（走 --mcp-config，与 DSH 不同）─────


def test_claude_kernel_builds_mcp_config_file():
    """Claude Code 不支持 ACP 的 mcp_servers 参数，只认 `--mcp-config <json文件>`。

    格式：{"mcpServers": {"<name>": {"type": "http", "url": ..., "headers": {...}}}}
    """
    import json
    import os

    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    path, env = ClaudeCodeKernel()._build_mcp_config()
    assert path, "应该生成配置文件"
    try:
        data = json.load(open(path))
        assert "ethan" in data["mcpServers"]
        server = data["mcpServers"]["ethan"]
        assert server["type"] == "http"
        assert server["url"].endswith("/kernel-tools/")
    finally:
        os.unlink(path)


def test_claude_mcp_config_respects_off(monkeypatch):
    import ethan.core.config as cfg_mod
    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    cfg = cfg_mod.get_config()
    monkeypatch.setattr(cfg.defaults.kernel, "share_tools", "off", raising=False)
    path, _ = ClaudeCodeKernel()._build_mcp_config()
    assert path == ""


def test_claude_mcp_config_contains_api_key(monkeypatch):
    """配置里要带鉴权头，否则 /kernel-tools 返回 401。"""
    import json
    import os

    import ethan.core.config as cfg_mod
    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    cfg = cfg_mod.get_config()
    monkeypatch.setattr(cfg.network, "mcp_api_key", "test-key-123", raising=False)

    path, _ = ClaudeCodeKernel()._build_mcp_config()
    assert path
    try:
        data = json.load(open(path))
        hdr = data["mcpServers"]["ethan"]["headers"]
        assert hdr["Authorization"] == "Bearer test-key-123"
    finally:
        os.unlink(path)


def test_claude_agent_passes_mcp_config_flag():
    """`_run_claude_code` 收到 mcp_config_path 时必须拼进命令行。

    注意不能加 `--strict-mcp-config`：那会忽略用户 ~/.claude 里配的 MCP server，
    我们只是"额外挂一个"，不该把别人的丢掉。
    """
    import inspect

    from ethan.acp import agent_claude

    src = inspect.getsource(agent_claude._run_claude_code)
    assert '"--mcp-config"' in src, "必须拼进命令行"
    # 注释里会提到 strict 但不能真的拼进 cmd
    cmd_lines = [ln for ln in src.splitlines() if "cmd" in ln and "strict" in ln]
    assert not cmd_lines, "不该把 --strict-mcp-config 拼进命令（会丢掉用户自己的 MCP 配置）"


def test_claude_mcp_requires_skip_permissions():
    """实测：不加 --dangerously-skip-permissions 时 MCP 工具调用会被拦。

    现象是 Claude 回「工具还没获得授权，这次调用被拦下了」——注册成功了但用不了。
    """
    import inspect

    from ethan.acp import agent_claude

    src = inspect.getsource(agent_claude._run_claude_code)
    assert "--dangerously-skip-permissions" in src


# ── 能力声明：哪些内核真的能共享 Ethan 工具 ──────────────────


def test_shares_ethan_tools_declared_for_all_kernels():
    """每个内核都要明确声明能否共享，不能留默认值糊过去。

    实测结论（2026-11-15）：
      ethan       ✅ 本来就是
      dsh         ✅ ACP mcp_servers
      claude_code ✅ --mcp-config
      codex       ❌ 接受配置但不加载工具
      opencode    ❌ 只能写全局配置（会污染用户环境）
      pi          ❌ 源码里没有 MCP
    """
    from ethan.kernel.runtime import get_kernel_registry

    expect_yes = {"ethan", "dsh", "claude_code"}
    expect_no = {"codex", "opencode", "pi"}

    for item in get_kernel_registry().list_status():
        kind = item["kind"]
        caps = item["capabilities"]
        if kind in expect_yes:
            assert caps["shares_ethan_tools"] is True, f"{kind} 应该能共享 Ethan 工具"
        elif kind in expect_no:
            assert caps["shares_ethan_tools"] is False, f"{kind} 不能共享，别谎报"
            assert caps["shares_ethan_tools_reason"], (
                f"{kind} 不能共享时必须给出原因（不能只说「不支持」）"
            )


def test_unsupported_reasons_are_actionable():
    """不能共享时给的原因要能让用户做决定，不是一句「暂不支持」。"""
    from ethan.kernel.runtime import get_kernel_registry

    for item in get_kernel_registry().list_status():
        caps = item["capabilities"]
        if caps["shares_ethan_tools"]:
            continue
        reason = caps["shares_ethan_tools_reason"]
        assert len(reason) > 15, f"{item['kind']} 的原因太笼统：{reason!r}"
        # 应该提到具体原因或给出替代方案
        assert any(
            kw in reason for kw in ("实测", "不支持", "建议", "污染", "无法")
        ), f"{item['kind']} 的原因没有解释清楚：{reason!r}"
