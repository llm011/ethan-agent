"""First-time user onboarding detection and messaging."""
from pathlib import Path

from ethan.core.config import get_config, CONFIG_DIR


def is_first_time() -> bool:
    """Returns True if this looks like a fresh installation.

    Criteria: facts.json is absent/empty AND agent_name is the default "Ethan".
    """
    facts_file = CONFIG_DIR / "memory" / "facts.json"
    config = get_config()
    no_facts = not facts_file.exists() or facts_file.read_text(encoding="utf-8").strip() in ("[]", "")
    default_name = config.defaults.agent_name == "Ethan"
    return no_facts and default_name


ONBOARDING_MESSAGE = """👋 Hi! I'm your new AI partner. Before we get started, let me ask a couple of quick questions:

1. What would you like to call me? (default: Ethan)
2. What's your name and what do you do? (e.g., "I'm Alex, a software engineer")

This helps me personalize our experience together. You can always change these in Settings later."""
