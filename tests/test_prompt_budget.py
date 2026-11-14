"""system prompt 体积护栏测试。

这类测试的价值不在「跑通」，而在**有人往 prompt 里塞东西时立刻失败**。
v2 PR 曾声称「Context 占用 ~6KB → ~300B (-95%)」，实际一个模块都没接进主链路，
指标是假的。这里锁的是真实测量值。
"""
from __future__ import annotations

import pytest

from ethan.skills.registry import SkillRegistry
from tests.bench_prompt_size import BUDGETS, TOTAL_BUDGET, check, measure_prompt


@pytest.fixture(scope="module")
def measured():
    return measure_prompt()


def test_prompt_within_budget(measured):
    problems = check(measured)
    assert not problems, "system prompt 超预算：\n" + "\n".join(problems)


def test_total_prompt_not_regressed(measured):
    """硬上限：超过就说明又有整块内容被塞进每轮 prompt。"""
    assert measured["total"] <= TOTAL_BUDGET


def test_tools_reference_within_budget(measured):
    """tools.md 是最大单一来源，必须单独盯。"""
    assert measured["blocks"].get("tools_reference", 0) <= BUDGETS["tools_reference"]


def test_available_skills_is_tiered(measured):
    """技能索引必须是分级形态——全量带描述时这块会到 12.5K。"""
    assert measured["blocks"].get("available_skills", 0) <= BUDGETS["available_skills"]


# ── build_index_block 行为 ───────────────────────────────────


def test_index_block_splits_hot_and_cold():
    registry = SkillRegistry()
    registry.load()
    hot, cold = registry.build_index_block()
    assert hot, "至少应有高频技能（fast_path 或历史命中）"
    # 热行带描述，冷行只有名字
    assert all(line.startswith("- ") for line in hot)
    assert all(not line.startswith("-") for line in cold)
    # 两组不重叠，且覆盖全部 default 类技能
    total = len(hot) + len(cold)
    default_count = sum(1 for s in registry.all() if getattr(s, "category", "default") == "default")
    assert total == default_count


def test_index_block_cold_entries_are_names_only():
    registry = SkillRegistry()
    registry.load()
    _, cold = registry.build_index_block()
    for name in cold:
        assert ":" not in name, f"冷门技能应只给名字，实际：{name}"


def test_index_block_respects_desc_cap():
    registry = SkillRegistry()
    registry.load()
    hot, _ = registry.build_index_block(desc_chars=10)
    for line in hot:
        if ": " in line:
            desc = line.split(": ", 1)[1]
            assert len(desc) <= 11, f"描述未按 cap 截断：{line}"
