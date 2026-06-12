import re
with open('../ethan/core/agent.py', 'r') as f:
    content = f.read()

new_build_system = '''    def _build_system(self, messages: list[Message]) -> str:
        """构建 system prompt，注入时间、长期记忆、Skills、Procedures。"""
        import os
        from pathlib import Path

        system_dir = Path(os.path.expanduser("~/.ethan/system"))
        identity_path = system_dir / "identity.md"
        soul_path = system_dir / "soul.md"

        identity_content = ""
        if identity_path.exists():
            identity_content = identity_path.read_text(encoding="utf-8").strip()

        soul_content = ""
        if soul_path.exists():
            soul_content = soul_path.read_text(encoding="utf-8").strip()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        
        parts = []
        if identity_content:
            parts.append(f"<identity>\\n{identity_content}\\n</identity>")
        elif self._base_system:
            parts.append(self._base_system)
            
        if soul_content:
            parts.append(f"<operating_principles>\\n{soul_content}\\n</operating_principles>")
            
        parts.append(f"Current time: {now}")

        # Long-term facts (cold memory) — injected for all interfaces
        facts_ctx = self._facts.build_context(max_facts=15)
        if facts_ctx:
            parts.append(f"<user_context>\\n{facts_ctx}\\n</user_context>")

        # Procedural memory
        proc_ctx = self._procedures.build_context()
        if proc_ctx:
            parts.append(f"<procedures>\\n{proc_ctx}\\n</procedures>")

        # Skills
        if self._skills and messages:
            last_user = ""
            for m in reversed(messages):
                if m.role == "user" and m.content:
                    last_user = m.content
                    break
            if last_user:
                skill_ctx = self._skills.build_context(last_user)
                if skill_ctx:
                    parts.append(f"<relevant_skills>\\n{skill_ctx}\\n</relevant_skills>")

        return "\\n\\n".join(parts)'''

# Replace the method
import re
pattern = re.compile(r'    def _build_system\(self, messages: list\[Message\]\) -> str:(.*?)(?=    def async)', re.DOTALL | re.MULTILINE)
# Since `async def chat` is next, we can use that to anchor
pattern = re.compile(r'    def _build_system\(self, messages: list\[Message\]\) -> str:.*?    async def chat', re.DOTALL)

if pattern.search(content):
    content = pattern.sub(new_build_system + '\n\n    async def chat', content)
    with open('../ethan/core/agent.py', 'w') as f:
        f.write(content)
    print("Replaced successfully")
else:
    print("Could not find method to replace")
