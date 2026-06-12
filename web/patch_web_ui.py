import re

with open('../web/components/settings-view.tsx', 'r') as f:
    content = f.read()

# Replace imports
content = content.replace(
    'import { fetchAgentSettings, updateAgentSettings, AgentSettings } from "@/lib/api";',
    'import { fetchAgentSettings, updateAgentSettings, AgentSettings, fetchSystemSettings, updateSystemSettings, SystemSettings } from "@/lib/api";'
)

# Add new state
content = content.replace(
    '  const [form, setForm] = useState<AgentSettings>({\n    agent_name: "",\n    system_prompt: "",\n    language: "zh",\n    default_model: "",\n  });',
    '''  const [form, setForm] = useState<AgentSettings>({
    agent_name: "",
    system_prompt: "",
    language: "zh",
    default_model: "",
  });
  const [sysForm, setSysForm] = useState<SystemSettings>({
    identity: "",
    soul: "",
  });'''
)

# Update useEffect
content = content.replace(
    '''  useEffect(() => {
    fetchAgentSettings()
      .then((data) => setForm(data))
      .catch(() => setMessage({ type: "error", text: "加载设置失败" }))
      .finally(() => setLoading(false));
  }, []);''',
    '''  useEffect(() => {
    Promise.all([fetchAgentSettings(), fetchSystemSettings()])
      .then(([agentData, sysData]) => {
        setForm(agentData);
        setSysForm(sysData);
      })
      .catch(() => setMessage({ type: "error", text: "加载设置失败" }))
      .finally(() => setLoading(false));
  }, []);'''
)

# Update handleSave
content = content.replace(
    '''  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await updateAgentSettings(form);
      setMessage({ type: "success", text: "设置已保存" });
    } catch {
      setMessage({ type: "error", text: "保存失败，请重试" });
    } finally {
      setSaving(false);
      setTimeout(() => setMessage(null), 3000);
    }
  };''',
    '''  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await Promise.all([
        updateAgentSettings(form),
        updateSystemSettings(sysForm)
      ]);
      setMessage({ type: "success", text: "设置已保存" });
    } catch {
      setMessage({ type: "error", text: "保存失败，请重试" });
    } finally {
      setSaving(false);
      setTimeout(() => setMessage(null), 3000);
    }
  };'''
)

# Replace the System Prompt textarea with Identity and Soul
old_textarea = '''          {/* System Prompt */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">System Prompt</label>
            <textarea
              rows={8}
              value={form.system_prompt}
              onChange={(e) => setForm((prev) => ({ ...prev, system_prompt: e.target.value }))}
              placeholder="输入系统提示词..."
              className="w-full resize-y bg-muted border border-border rounded-xl px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
            <p className="text-xs text-muted-foreground">(每次对话注入到 system prompt)</p>
          </div>'''

new_textareas = '''          {/* Identity (~/.ethan/system/identity.md) */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Identity (Core Persona)</label>
            <textarea
              rows={6}
              value={sysForm.identity}
              onChange={(e) => setSysForm((prev) => ({ ...prev, identity: e.target.value }))}
              placeholder="定义核心人格（Ethan、数字实体等）..."
              className="w-full resize-y bg-muted border border-border rounded-xl px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-ring font-mono"
            />
            <p className="text-xs text-muted-foreground">存储于 ~/.ethan/system/identity.md</p>
          </div>

          {/* Soul (~/.ethan/system/soul.md) */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Soul (Operating Principles)</label>
            <textarea
              rows={10}
              value={sysForm.soul}
              onChange={(e) => setSysForm((prev) => ({ ...prev, soul: e.target.value }))}
              placeholder="定义执行原则（Loop、ReAct、Error Handling等）..."
              className="w-full resize-y bg-muted border border-border rounded-xl px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-ring font-mono"
            />
            <p className="text-xs text-muted-foreground">存储于 ~/.ethan/system/soul.md，建议包含正反示例</p>
          </div>'''

content = content.replace(old_textarea, new_textareas)

with open('../web/components/settings-view.tsx', 'w') as f:
    f.write(content)

print("Web UI patched")
