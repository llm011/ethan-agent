"""First-time user onboarding detection and messaging."""
from ethan.core.config import get_config, CONFIG_DIR


def is_first_time() -> bool:
    """Returns True if this looks like a fresh installation."""
    facts_file = CONFIG_DIR / "memory" / "facts.json"
    config = get_config()
    no_facts = not facts_file.exists() or facts_file.read_text(encoding="utf-8").strip() in ("[]", "")
    default_name = config.defaults.agent_name == "Ethan"
    return no_facts and default_name


def needs_provider_setup() -> bool:
    """Returns True if no provider has an API key configured."""
    config = get_config()
    return not any(p.api_key for p in config.providers.values())


ONBOARDING_MESSAGE = """\
Welcome! Before we start, let me ask a couple of quick questions.
You can always change these later via `ethan provider set` or in Web UI Settings."""
