"""dida_tools（滴答清单 CLI wrapper）测试。

测试不依赖真实 dida 账户：mock `_run_dida` 验证参数构造与 JSON 解析逻辑，
另用真实 `_run_dida` 验证「dida 未安装」时的友好引导。
"""
import asyncio

from ethan.tools.builtin.dida_tools import (
    DidaProjectListTool,
    DidaTaskCompleteTool,
    DidaTaskCreateTool,
    DidaTaskListTool,
    _run_dida,
)


def _run(coro):
    return asyncio.run(coro)


# -- _run_dida：未安装 dida 时的引导 ---------------------------------

def test_run_dida_missing_bin(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    out = _run(_run_dida(["project", "list"]))
    assert isinstance(out, str)
    assert "dida-cli" in out and "npm install -g" in out


# -- DidaProjectListTool ----------------------------------------------

def test_project_list_formats_json(monkeypatch):
    async def fake(args):
        assert args == ["project", "list", "--json"]
        return '[{"id":"p1","name":"工作","kind":"TASK"},{"id":"p2","name":"生活","kind":"TASK"}]'
    monkeypatch.setattr("ethan.tools.builtin.dida_tools._run_dida", fake)
    out = _run(DidaProjectListTool().run(json_output=False))
    assert "p1: 工作" in out
    assert "p2: 生活" in out


def test_project_list_json_output(monkeypatch):
    async def fake(args):
        assert args == ["project", "list", "--json"]
        return '[{"id":"p1","name":"工作"}]'
    monkeypatch.setattr("ethan.tools.builtin.dida_tools._run_dida", fake)
    out = _run(DidaProjectListTool().run(json_output=True))
    assert out.startswith("[{")  # 透传原始 JSON


def test_project_list_empty(monkeypatch):
    async def fake(args):
        return "[]"
    monkeypatch.setattr("ethan.tools.builtin.dida_tools._run_dida", fake)
    out = _run(DidaProjectListTool().run())
    assert "没有找到清单" in out


# -- DidaTaskCreateTool -----------------------------------------------

def test_task_create_builds_args(monkeypatch):
    captured = {}

    async def fake(args):
        captured["args"] = args
        return '{"id":"t1","title":"买牛奶","projectId":"p1","dueDate":"2026-08-10T01:00:00.000Z","priority":3}'
    monkeypatch.setattr("ethan.tools.builtin.dida_tools._run_dida", fake)
    out = _run(DidaTaskCreateTool().run(
        title="买牛奶", project="p1", due_date="2026-08-10T01:00:00Z", priority=3, tags="工作,紧急",
    ))
    assert captured["args"][0] == "task" and captured["args"][1] == "create"
    assert "--title" in captured["args"] and "买牛奶" in captured["args"]
    assert captured["args"][captured["args"].index("--due-date") + 1] == "2026-08-10T01:00:00Z"
    assert captured["args"][captured["args"].index("--priority") + 1] == "3"
    assert captured["args"][captured["args"].index("--tags") + 1] == "工作,紧急"
    assert "已创建任务" in out and "t1" in out


def test_task_create_required(monkeypatch):
    async def fake(args):
        return '{"id":"t1","title":"x","projectId":"p1"}'
    monkeypatch.setattr("ethan.tools.builtin.dida_tools._run_dida", fake)
    out = _run(DidaTaskCreateTool().run(title="x", project="p1"))
    assert "已创建任务" in out


# -- DidaTaskListTool -------------------------------------------------

def test_task_list_search(monkeypatch):
    captured = {}
    payload = (
        '[{"id":"t1","title":"季度报告","projectId":"p1","dueDate":"2026-08-10","priority":5,"status":0},'
        '{"id":"t2","title":"周报","projectId":"p2","dueDate":null,"priority":0,"status":0}]'
    )

    async def fake(args):
        captured["args"] = args
        return payload
    monkeypatch.setattr("ethan.tools.builtin.dida_tools._run_dida", fake)
    out = _run(DidaTaskListTool().run(keyword="报告", projects="p1", status="0"))
    assert captured["args"] == ["task", "search", "报告", "--json", "--projects", "p1", "--status", "0"]
    assert "t1: 季度报告" in out
    assert "t2: 周报" in out


def test_task_list_filter(monkeypatch):
    captured = {}

    async def fake(args):
        captured["args"] = args
        return "[]"
    monkeypatch.setattr("ethan.tools.builtin.dida_tools._run_dida", fake)
    out = _run(DidaTaskListTool().run(projects="p1"))
    assert captured["args"] == ["task", "filter", "--json", "--projects", "p1"]
    assert "没有找到匹配的任务" in out


# -- DidaTaskCompleteTool ----------------------------------------------

def test_task_complete(monkeypatch):
    captured = {}

    async def fake(args):
        captured["args"] = args
        return "ok"
    monkeypatch.setattr("ethan.tools.builtin.dida_tools._run_dida", fake)
    out = _run(DidaTaskCompleteTool().run(project="p1", task_id="t1"))
    assert captured["args"] == ["task", "complete", "p1", "t1"]
    assert "已完成任务 t1" in out


# -- agent_factory 注册受 DIDA_ENABLED 控制 ------------------------------
def test_agent_factory_gates_dida_registration(monkeypatch):
    """验证 build_tool_registry 在 dida.enabled 时注册 dida 工具、否则不注册。"""
    from ethan.core.agent_factory import build_tool_registry

    class _Cfg:
        class _Dida:
            enabled = True
        class _WebSearch:
            image_search_enabled = False  # 避免 image_search 干扰断言
        tools = type("_Tools", (), {"dida": _Dida(), "web_search": _WebSearch()})()

    monkeypatch.setattr("ethan.core.config.get_config", lambda: _Cfg())
    reg = build_tool_registry()
    names = {t.name for t in reg.all()}
    assert "dida_project_list" in names
    assert "dida_task_create" in names
    assert "dida_task_list" in names
    assert "dida_task_complete" in names

    class _CfgOff:
        class _Dida:
            enabled = False
        class _WebSearch:
            image_search_enabled = False
        tools = type("_Tools", (), {"dida": _Dida(), "web_search": _WebSearch()})()

    monkeypatch.setattr("ethan.core.config.get_config", lambda: _CfgOff())
    reg2 = build_tool_registry()
    names2 = {t.name for t in reg2.all()}
    assert not ({"dida_project_list", "dida_task_create", "dida_task_list", "dida_task_complete"} & names2)


# -- plugin remove: boolean 字段置 False 而非空字符串 -----------------

def test_clear_plugin_config_boolean_sets_false():
    """plugin remove 时 boolean 字段应置 False，而非空字符串（避免 pydantic bool_parsing 崩溃）。"""
    from ethan.core.config import Config
    from ethan.interface.commands.plugin import PLUGIN_REGISTRY, _clear_plugin_config

    cfg = Config()
    cfg.tools.dida.enabled = True
    _clear_plugin_config(cfg, PLUGIN_REGISTRY["dida"])
    assert cfg.tools.dida.enabled is False
    saved = cfg.model_dump()
    assert saved["tools"]["dida"]["enabled"] is False
