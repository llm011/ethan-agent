import re

with open('../ethan/interface/api.py', 'r') as f:
    content = f.read()

# Add endpoints for /settings/system
system_endpoints = '''
class SystemSettingsPatch(BaseModel):
    identity: str | None = None
    soul: str | None = None

@app.get("/settings/system", dependencies=[Depends(verify_token)])
async def get_system_settings():
    from pathlib import Path
    import os
    system_dir = Path(os.path.expanduser("~/.ethan/system"))
    identity_path = system_dir / "identity.md"
    soul_path = system_dir / "soul.md"
    
    identity = identity_path.read_text(encoding="utf-8") if identity_path.exists() else ""
    soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
    
    return {
        "identity": identity,
        "soul": soul
    }

@app.patch("/settings/system", dependencies=[Depends(verify_token)])
async def update_system_settings(req: SystemSettingsPatch):
    from pathlib import Path
    import os
    system_dir = Path(os.path.expanduser("~/.ethan/system"))
    system_dir.mkdir(parents=True, exist_ok=True)
    
    if req.identity is not None:
        (system_dir / "identity.md").write_text(req.identity, encoding="utf-8")
    if req.soul is not None:
        (system_dir / "soul.md").write_text(req.soul, encoding="utf-8")
        
    return {"ok": True}
'''

# Insert the new endpoints after the agent settings patch
pattern = re.compile(r'    reload_config\(\)\n    return \{"ok": True\}')
if pattern.search(content):
    content = content[:pattern.search(content).end()] + '\n\n' + system_endpoints + content[pattern.search(content).end():]
    with open('../ethan/interface/api.py', 'w') as f:
        f.write(content)
    print("API patched")
else:
    print("Could not find insertion point")
