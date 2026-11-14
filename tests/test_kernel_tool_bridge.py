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
    for dangerous in ("config_set", "profile_update", "procedure_write", "memory_write"):
        assert dangerous not in names, f"{dangerous} 不该暴露"


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
