"""ACP data models."""
from dataclasses import dataclass, field


@dataclass
class ACPResult:
    success: bool
    output: str
    agent: str
    session_id: str = ""
    sub_steps: list = field(default_factory=list)
