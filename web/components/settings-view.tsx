"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sun, Moon } from "lucide-react";
import {
  fetchAgentSettings, updateAgentSettings, AgentSettings,
  fetchSystemSettings, updateSystemSettings, SystemSettings,
  fetchProviderSettings, updateProviderSettings, ProviderSettings,
  fetchSystemPromptPreview,
} from "@/lib/api";

function useTheme() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem("ethan-theme") as "dark" | "light") || "dark";
    }
    return "dark";
  });

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("ethan-theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
      document.documentElement.classList.toggle("light", next === "light");
      return next;
    });
  }, []);

  return { theme, toggle };
}

interface SettingsViewProps {
  models: { id: string; description: string }[];
}

type TabType = "general" | "providers" | "identity" | "soul" | "tools" | "heartbeat" | "prompt-preview";

function PromptPreview() {
  const [data, setData] = useState<{ system_prompt: string; approx_tokens: number; chars: number } | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const d = await fetchSystemPromptPreview();
      setData(d);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="h-full flex flex-col min-h-[500px]">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-lg font-medium">Prompt 预览</h3>
        <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
          {loading ? "加载中..." : "刷新"}
        </Button>
      </div>
      {data && (
        <p className="text-xs text-muted-foreground mb-3">
          每轮对话 system prompt 约 <span className="font-mono text-foreground">{data.approx_tokens.toLocaleString()}</span> tokens（{data.chars.toLocaleString()} 字符）
        </p>
      )}
      <pre className="flex-1 text-xs font-mono bg-muted/40 rounded-lg p-4 overflow-auto whitespace-pre-wrap leading-relaxed text-muted-foreground">
        {data ? data.system_prompt : (loading ? "加载中..." : "")}
      </pre>
    </div>
  );
}


export function SettingsView({ models }: SettingsViewProps) {
  const [activeTab, setActiveTab] = useState<TabType>("general");
  const { theme, toggle: toggleTheme } = useTheme();
  
  const [agentForm, setAgentForm] = useState<AgentSettings>({
    workspace: "",
    agent_name: "",
    system_prompt: "",
    language: "zh",
    default_model: "",
    heartbeat_enabled: true,
    heartbeat_interval_minutes: 10,
    proxy: "",
    max_tokens: 4096,
    max_tool_iterations: 10,
    fast_keywords: [],
    fast_max_length: 12,
    fast_skill_triggers: [],
  });
  
  const [sysForm, setSysForm] = useState<SystemSettings>({
    identity: "",
    soul: "",
    format: "",
    tools: "",
    heartbeat: "",
  });

  const [providerForm, setProviderForm] = useState<ProviderSettings>({});

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    Promise.all([fetchAgentSettings(), fetchSystemSettings(), fetchProviderSettings()])
      .then(([agentData, sysData, providerData]) => {
        setAgentForm({
          ...agentData,
          heartbeat_enabled: agentData.heartbeat_enabled ?? true,
          heartbeat_interval_minutes: agentData.heartbeat_interval_minutes ?? 10,
        });
        setSysForm(sysData);
        setProviderForm(providerData);
      })
      .catch(() => setMessage({ type: "error", text: "加载设置失败" }))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await Promise.all([
        updateAgentSettings(agentForm),
        updateSystemSettings(sysForm),
        updateProviderSettings(providerForm)
      ]);
      setMessage({ type: "success", text: "设置已保存" });
      setTimeout(() => setMessage(null), 3000);
    } catch {
      setMessage({ type: "error", text: "保存失败，请重试" });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="p-4 text-muted-foreground">Loading settings...</div>;

  const tabs = [
    { id: "general", label: "通用设置 (General)" },
    { id: "providers", label: "模型配置 (Providers)" },
    { id: "identity", label: "身份设定 (Identity)" },
    { id: "soul", label: "运行准则 (Soul)" },
    { id: "tools", label: "工具说明 (Tools)" },
    { id: "heartbeat", label: "心跳任务 (Heartbeat)" },
    { id: "prompt-preview", label: "System Prompt 预览" },
  ];

  return (
    <div className="flex h-full w-full bg-background overflow-hidden border rounded-md">
      {/* Sidebar */}      <div className="w-[200px] border-r bg-muted/30 flex flex-col">
        <div className="p-4 border-b">
          <h2 className="font-semibold">设置</h2>
        </div>
        <div className="flex-1 py-2">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as TabType)}
              className={`w-full text-left px-4 py-2 text-sm transition-colors hover:bg-muted/50 ${
                activeTab === tab.id ? "bg-muted font-medium border-l-2 border-primary" : "text-muted-foreground border-l-2 border-transparent"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        <ScrollArea className="flex-1 p-6">
          <div className="max-w-3xl h-full flex flex-col gap-6">
            
            {activeTab === "general" && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium mb-4">通用设置</h3>
                  <div className="grid gap-4">
                    <div className="grid gap-2">
                      <label className="text-sm font-medium">Agent 名字</label>
                      <Input
                        value={agentForm.agent_name}
                        onChange={(e) => setAgentForm({ ...agentForm, agent_name: e.target.value })}
                        placeholder="Ethan"
                      />
                    </div>
                    
                    <div className="grid gap-2">
                      <label className="text-sm font-medium">工作区目录</label>
                      <Input
                        value={agentForm.workspace}
                        onChange={(e) => setAgentForm({ ...agentForm, workspace: e.target.value })}
                        placeholder="~/.ethan"
                      />
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">默认模型</label>
                      <Select
                        value={agentForm.default_model}
                        onValueChange={(val) => setAgentForm({ ...agentForm, default_model: val || "" })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="选择模型" />
                        </SelectTrigger>
                        <SelectContent>
                          {models.map((m) => (
                            <SelectItem key={m.id} value={m.id}>
                              {m.description || m.id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">外观</label>
                      <div className="flex items-center gap-3">
                        <Button
                          variant="outline"
                          className="flex items-center gap-2"
                          onClick={toggleTheme}
                        >
                          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                          {theme === "dark" ? "切换到日间模式" : "切换到暗黑模式"}
                        </Button>
                        <span className="text-xs text-muted-foreground">当前：{theme === "dark" ? "暗黑模式" : "日间模式"}</span>
                      </div>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">语言</label>
                      <Select
                        value={agentForm.language}
                        onValueChange={(val) => setAgentForm({ ...agentForm, language: val || "" })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Language" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="zh">中文</SelectItem>
                          <SelectItem value="en">English</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">心跳间隔（分钟）</label>
                      <div className="flex items-center gap-3">
                        <input
                          type="number"
                          min={1}
                          max={1440}
                          value={agentForm.heartbeat_interval_minutes ?? 10}
                          onChange={(e) => setAgentForm({ ...agentForm, heartbeat_interval_minutes: parseInt(e.target.value) || 10 })}
                          className="w-24 bg-background border border-border rounded-md px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                        />
                        <label className="flex items-center gap-2 text-sm cursor-pointer">
                          <input
                            type="checkbox"
                            checked={agentForm.heartbeat_enabled ?? true}
                            onChange={(e) => setAgentForm({ ...agentForm, heartbeat_enabled: e.target.checked })}
                            className="w-4 h-4"
                          />
                          启用心跳
                        </label>
                      </div>
                      <p className="text-xs text-muted-foreground">系统级定时维护：facts 去重整理 + 执行 heartbeat.md 中的任务</p>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">网络代理</label>
                      <Input
                        value={agentForm.proxy ?? ""}
                        onChange={(e) => setAgentForm({ ...agentForm, proxy: e.target.value })}
                        placeholder="http://127.0.0.1:7890"
                      />
                      <p className="text-xs text-muted-foreground">留空则不使用代理</p>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">高级参数</label>
                      <div className="flex gap-4">
                        <div className="flex-1 grid gap-1">
                          <label className="text-xs text-muted-foreground">Max Tokens</label>
                          <Input
                            type="number"
                            value={agentForm.max_tokens ?? 4096}
                            onChange={(e) => setAgentForm({ ...agentForm, max_tokens: parseInt(e.target.value) || 4096 })}
                          />
                        </div>
                        <div className="flex-1 grid gap-1">
                          <label className="text-xs text-muted-foreground">Max Tool Iterations</label>
                          <Input
                            type="number"
                            value={agentForm.max_tool_iterations ?? 10}
                            onChange={(e) => setAgentForm({ ...agentForm, max_tool_iterations: parseInt(e.target.value) || 10 })}
                          />
                        </div>
                      </div>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">Fast-path 关键词</label>
                      <p className="text-xs text-muted-foreground">命中这些关键词且消息长度 ≤ {agentForm.fast_max_length} 字时走快捷路径（不调工具，直接回复）。支持通配符 *，如 "关*灯"。每行一个。</p>
                      <textarea
                        className="font-mono text-sm bg-background border border-border rounded-md px-3 py-2 outline-none focus:ring-2 focus:ring-ring resize-none"
                        rows={6}
                        value={(agentForm.fast_keywords ?? []).join("\n")}
                        onChange={(e) => setAgentForm({ ...agentForm, fast_keywords: e.target.value.split("\n").map(s => s.trim()).filter(Boolean) })}
                        placeholder={"关*灯\n开*灯\n..."}
                      />
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-muted-foreground">最大消息长度</label>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          value={agentForm.fast_max_length ?? 12}
                          onChange={(e) => setAgentForm({ ...agentForm, fast_max_length: parseInt(e.target.value) || 12 })}
                          className="w-20 bg-background border border-border rounded-md px-2 py-1 text-sm outline-none"
                        />
                        <span className="text-xs text-muted-foreground">字</span>
                      </div>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">Fast-path Skill 触发词</label>
                      <p className="text-xs text-muted-foreground">命中这些关键词时强制走快捷路径，不受消息长度限制。适合绑定 Home Assistant 等确定性 Skill 命令。支持通配符 *。每行一个。</p>
                      <textarea
                        className="font-mono text-sm bg-background border border-border rounded-md px-3 py-2 outline-none focus:ring-2 focus:ring-ring resize-none"
                        rows={4}
                        value={(agentForm.fast_skill_triggers ?? []).join("\n")}
                        onChange={(e) => setAgentForm({ ...agentForm, fast_skill_triggers: e.target.value.split("\n").map(s => s.trim()).filter(Boolean) })}
                        placeholder={"打开客厅灯\n关闭空调\n..."}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeTab === "providers" && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium mb-4">模型提供商配置</h3>
                  <div className="space-y-6">
                    {Object.entries(providerForm).map(([key, config]) => (
                      <div key={key} className="border p-4 rounded-md space-y-4">
                        <h4 className="font-medium text-sm capitalize">{key}</h4>
                        <div className="grid gap-3">
                          <div className="grid gap-2">
                            <label className="text-xs text-muted-foreground">API Key</label>
                            <Input
                              type="password"
                              value={config.api_key || ""}
                              onChange={(e) => setProviderForm({
                                ...providerForm,
                                [key]: { ...config, api_key: e.target.value }
                              })}
                              placeholder="sk-..."
                            />
                          </div>
                          <div className="grid gap-2">
                            <label className="text-xs text-muted-foreground">Base URL (可选)</label>
                            <Input
                              value={config.base_url || ""}
                              onChange={(e) => setProviderForm({
                                ...providerForm,
                                [key]: { ...config, base_url: e.target.value || null }
                              })}
                              placeholder="https://api.example.com"
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {activeTab === "identity" && (
              <div className="h-full flex flex-col min-h-[500px]">
                <h3 className="text-lg font-medium mb-2">身份设定 (identity.md)</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  定义 Agent 的核心身份、角色扮演、说话语气等基本特征。
                </p>
                <Textarea
                  className="flex-1 font-mono text-sm resize-none"
                  value={sysForm.identity}
                  onChange={(e) => setSysForm({ ...sysForm, identity: e.target.value })}
                  placeholder="You are Ethan..."
                />
              </div>
            )}

            {activeTab === "soul" && (
              <div className="h-full flex flex-col min-h-[500px]">
                <h3 className="text-lg font-medium mb-2">运行准则 (soul.md)</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  定义 Agent 处理问题的思维方式、工作流原则、安全准则等深层认知逻辑。
                </p>
                <Textarea
                  className="flex-1 font-mono text-sm resize-none"
                  value={sysForm.soul}
                  onChange={(e) => setSysForm({ ...sysForm, soul: e.target.value })}
                  placeholder="Thinking process..."
                />
              </div>
            )}

            {activeTab === "tools" && (
              <div className="h-full flex flex-col min-h-[500px]">
                <h3 className="text-lg font-medium mb-2">工具说明 (tools.md)</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  补充描述 Agent 可用的工具及使用原则，注入到系统 prompt 的 &lt;tools_reference&gt; 标签中。
                </p>
                <Textarea
                  className="flex-1 font-mono text-sm resize-none"
                  value={sysForm.tools}
                  onChange={(e) => setSysForm({ ...sysForm, tools: e.target.value })}
                  placeholder="- shell: 执行 shell 命令..."
                />
              </div>
            )}

            {activeTab === "heartbeat" && (
              <div className="h-full flex flex-col min-h-[500px]">
                <h3 className="text-lg font-medium mb-2">心跳任务 (heartbeat.md)</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  每次心跳时执行的周期性任务，由 Agent 自主维护。以 # 开头的行是注释不会执行。
                </p>
                <Textarea
                  className="flex-1 font-mono text-sm resize-none"
                  value={sysForm.heartbeat}
                  onChange={(e) => setSysForm({ ...sysForm, heartbeat: e.target.value })}
                  placeholder="# 在这里添加心跳任务..."
                />
              </div>
            )}

            {activeTab === "prompt-preview" && (
              <PromptPreview />
            )}

          </div>
        </ScrollArea>
        
        <div className="p-4 border-t bg-background flex items-center justify-between mt-auto">
          <div className="text-sm">
            {message && (
              <span className={message.type === "success" ? "text-green-500" : "text-red-500"}>
                {message.text}
              </span>
            )}
          </div>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "保存中..." : "保存设置"}
          </Button>
        </div>
      </div>
    </div>
  );
}
