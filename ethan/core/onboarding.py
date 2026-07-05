"""First-time user onboarding detection and messaging."""
from ethan.core.config import get_config


def is_first_time(user_id: str = "") -> bool:
    """Returns True if this looks like a fresh installation for the given profile."""
    from ethan.core.paths import user_facts_path
    facts_file = user_facts_path()
    config = get_config()
    no_facts = not facts_file.exists() or facts_file.read_text(encoding="utf-8").strip() in ("[]", "")
    default_name = config.defaults.agent_name == "Ethan"
    return no_facts and default_name


def mark_onboarded(user_id: str = "") -> None:
    """标记用户已完成 onboarding。

    is_first_time 依赖 facts.json 是否为空；onboarding 写入 fact 后即非首次。
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
