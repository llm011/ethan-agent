import re

with open("ethan/interface/api.py", "r", encoding="utf-8") as f:
    content = f.read()

# Agent settings
content = content.replace("class AgentSettingsPatch(BaseModel):", "class AgentSettingsPatch(BaseModel):\n    workspace: str | None = None")

content = content.replace("""    return {
        "system_prompt": config.defaults.system_prompt,
        "agent_name": config.defaults.agent_name,
        "language": config.defaults.language,
        "default_model": config.defaults.model,
    }""", """    return {
        "workspace": config.defaults.workspace,
        "system_prompt": config.defaults.system_prompt,
        "agent_name": config.defaults.agent_name,
        "language": config.defaults.language,
        "default_model": config.defaults.model,
    }""")

content = content.replace("""    if req.default_model is not None:
        config.defaults.model = req.default_model""", """    if req.default_model is not None:
        config.defaults.model = req.default_model
    if req.workspace is not None:
        config.defaults.workspace = req.workspace""")

# System settings
content = content.replace("    soul: str | None = None\n", "    soul: str | None = None\n    format: str | None = None\n")

content = content.replace("""    identity_path = system_dir / "identity.md"
    soul_path = system_dir / "soul.md"
    
    identity = identity_path.read_text(encoding="utf-8") if identity_path.exists() else ""
    soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
    
    return {
        "identity": identity,
        "soul": soul
    }""", """    identity_path = system_dir / "identity.md"
    soul_path = system_dir / "soul.md"
    format_path = system_dir / "format.md"
    
    identity = identity_path.read_text(encoding="utf-8") if identity_path.exists() else ""
    soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
    format_content = format_path.read_text(encoding="utf-8") if format_path.exists() else ""
    
    return {
        "identity": identity,
        "soul": soul,
        "format": format_content
    }""")

content = content.replace("""    if req.soul is not None:
        (system_dir / "soul.md").write_text(req.soul, encoding="utf-8")""", """    if req.soul is not None:
        (system_dir / "soul.md").write_text(req.soul, encoding="utf-8")
    if req.format is not None:
        (system_dir / "format.md").write_text(req.format, encoding="utf-8")""")

# Providers API
providers_api = """
@app.get("/settings/providers", dependencies=[Depends(verify_token)])
async def get_provider_settings():
    config = get_config()
    return {
        k: {
            "api_key": v.api_key,
            "base_url": v.base_url
        } for k, v in config.providers.items()
    }

@app.patch("/settings/providers", dependencies=[Depends(verify_token)])
async def update_provider_settings(req: dict[str, dict]):
    from ethan.core.config import ProviderConfig
    config = get_config()
    for k, v in req.items():
        if k not in config.providers:
            config.providers[k] = ProviderConfig()
        if "api_key" in v and v["api_key"] is not None:
            config.providers[k].api_key = v["api_key"]
        if "base_url" in v and v["base_url"] is not None:
            config.providers[k].base_url = v["base_url"]
    save_config(config)
    reload_config()
    return {"ok": True}
"""

content = content.replace("""@app.post("/upload", dependencies=[Depends(verify_token)])""", providers_api + "\n\n" + """@app.post("/upload", dependencies=[Depends(verify_token)])""")

with open("ethan/interface/api.py", "w", encoding="utf-8") as f:
    f.write(content)
