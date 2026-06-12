with open("ethan/core/agent.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("""        identity_path = system_dir / "identity.md"
        soul_path = system_dir / "soul.md\"""", """        identity_path = system_dir / "identity.md"
        soul_path = system_dir / "soul.md"
        format_path = system_dir / "format.md\"""")

content = content.replace("""        soul_content = ""
        if soul_path.exists():
            soul_content = soul_path.read_text(encoding="utf-8").strip()""", """        soul_content = ""
        if soul_path.exists():
            soul_content = soul_path.read_text(encoding="utf-8").strip()

        format_content = ""
        if format_path.exists():
            format_content = format_path.read_text(encoding="utf-8").strip()""")

content = content.replace("""        if soul_content:
            parts.append(f"<operating_principles>\\n{soul_content}\\n</operating_principles>\")""", """        if soul_content:
            parts.append(f"<operating_principles>\\n{soul_content}\\n</operating_principles>")
            
        if format_content:
            parts.append(f"<formatting_rules>\\n{format_content}\\n</formatting_rules>\")""")

with open("ethan/core/agent.py", "w", encoding="utf-8") as f:
    f.write(content)
