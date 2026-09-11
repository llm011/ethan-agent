"""First-time user onboarding detection and messaging."""
from ethan.core.config import get_config


def is_first_time(user_id: str = "") -> bool:
    """Returns True if this looks like a fresh installation for the given profile.

    判定：没有任何长期记忆（memories 表为空）且没有遗留 facts.json，
    且 agent 名还是默认值。facts.json 已退役，但迁移前的老安装仍可能只有它。
    """
    from ethan.core.paths import user_facts_path

    config = get_config()
    if config.defaults.agent_name != "Ethan":
        return False

    facts_file = user_facts_path()
    if facts_file.exists():
        try:
            if facts_file.read_text(encoding="utf-8").strip() not in ("[]", ""):
                return False
        except Exception:
            pass

    try:
        from ethan.memory.store import MemoryStore
        store = MemoryStore()
        try:
            if store.list_memories(status="active", limit=1):
                return False
        finally:
            store.close()
    except Exception:
        pass
    return True


def mark_onboarded(user_id: str = "") -> None:
    """标记用户已完成 onboarding。

    is_first_time 依赖长期记忆是否为空；onboarding 写入记忆后即非首次。
    此函数保留为显式标记位（目前 no-op，留作未来扩展）。
    """
    return None


def needs_provider_setup() -> bool:
    """Returns True if no provider has an API key configured."""
    config = get_config()
    return not any(p.api_key for p in config.providers.values())


ONBOARDING_MESSAGE = """\
Welcome! Before we start, let me ask a couple of quick questions.
You can always change these later via `ethan provider set` or in Web UI Settings."""
