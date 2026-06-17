"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sun, Moon } from "lucide-react";
import { MdEditor } from "@/components/md-editor";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  fetchAgentSettings, updateAgentSettings, AgentSettings,
  fetchSystemSettings, updateSystemSettings, SystemSettings,
  fetchProviderSettings, updateProviderSettings, ProviderSettings,
  fetchSystemPromptPreview, SystemPromptPreview,
  fetchChannels, patchChannel, ChannelInfo,
  fetchAPIKeys, createAPIKey, deleteAPIKey, APIKeyInfo, APIKeyCreated,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight } from "lucide-react";

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
  initialTab?: TabId;
}

type TabId = "general" | "providers" | "channels" | "identity" | "soul" | "tools" | "heartbeat" | "prompt-preview" | "api-keys";

const TAB_GROUPS = [
  {
    group: "基础配置",
    items: [
      { id: "general" as TabId, label: "通用" },
      { id: "providers" as TabId, label: "模型" },
      { id: "channels" as TabId, label: "渠道" },
    ],
  },
  {
    group: "系统提示词",
    items: [
      { id: "identity" as TabId, label: "身份设定" },
      { id: "soul" as TabId, label: "运行准则" },
      { id: "tools" as TabId, label: "工具说明" },
      { id: "heartbeat" as TabId, label: "心跳任务" },
    ],
  },
  {
    group: "开放接口",
    items: [
      { id: "api-keys" as TabId, label: "API Keys" },
    ],
  },
  {
    group: "调试",
    items: [
      { id: "prompt-preview" as TabId, label: "Prompt 预览" },
    ],
  },
];

const CHANNEL_FIELDS: Record<string, { key: string; label: string; secret?: boolean; placeholder?: string }[]> = {
  lark: [
    { key: "app_id", label: "App ID", placeholder: "cli_xxx" },
    { key: "app_secret", label: "App Secret", secret: true, placeholder: "xxxxxxxx" },
  ],
};

function PromptPreview() {
  const [data, setData] = useState<SystemPromptPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [promptView, setPromptView] = useState<"raw" | "md">("md");

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

  // Parse the prompt into sections split by XML-like tags.
  // Returns an array of {tag, content} — untagged content has tag = null.
  function parseSections(text: string): { tag: string | null; content: string }[] {
    const lines = text.split("\n");
    const sections: { tag: string | null; content: string }[] = [];
    let currentTag: string | null = null;
    let currentLines: string[] = [];

    for (const line of lines) {
      const openMatch = line.match(/^<([a-zA-Z_][a-zA-Z0-9_-]*)(?:\s[^>]*)?>$/);
      const closeMatch = line.match(/^<\/([a-zA-Z_][a-zA-Z0-9_-]*)>$/);

      if (openMatch) {
        if (currentLines.join("").trim()) {
          sections.push({ tag: currentTag, content: currentLines.join("\n").trim() });
        }
        currentTag = openMatch[1];
        currentLines = [];
      } else if (closeMatch) {
        sections.push({ tag: currentTag, content: currentLines.join("\n").trim() });
        currentTag = null;
        currentLines = [];
      } else {
        currentLines.push(line);
      }
    }
    if (currentLines.join("").trim()) {
      sections.push({ tag: currentTag, content: currentLines.join("\n").trim() });
    }
    return sections;
  }

  return (
    <div className="h-full flex flex-col min-h-[500px] gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Prompt 预览</h3>
        <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
          {loading ? "加载中..." : "刷新"}
        </Button>
      </div>

      {data && (
        <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm space-y-1">
          <div className="flex justify-between">
            <span className="text-muted-foreground">System prompt</span>
            <span className="font-mono">~{data.approx_tokens.toLocaleString()} tokens ({data.chars.toLocaleString()} 字符)</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Tools schema（{data.tool_count} 个工具）</span>
            <span className="font-mono">~{data.approx_tools_tokens.toLocaleString()} tokens</span>
          </div>
          <div className="border-t pt-1 mt-1 flex justify-between font-semibold">
            <span>Total（每轮 input 底线）</span>
            <span className="font-mono">~{data.approx_total_tokens.toLocaleString()} tokens</span>
          </div>
        </div>
      )}

      {data && (
        <div className="rounded-lg border overflow-hidden">
          <button
            className="w-full flex items-center justify-between px-4 py-2 text-sm font-medium bg-muted/30 hover:bg-muted/50 transition-colors"
            onClick={() => setToolsOpen(o => !o)}
          >
            <span>工具 Schema（{data.tool_count} 个）</span>
            <span className="text-muted-foreground text-xs">{toolsOpen ? "收起 ▲" : "展开 ▼"}</span>
          </button>
          {toolsOpen && (
            <div className="divide-y max-h-[400px] overflow-auto">
              {data.tools.map(tool => (
                <div key={tool.name} className="p-3 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold">{tool.name}</span>
                    {!tool.fast_path && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">full-path only</span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">{tool.description}</p>
                  <pre className="text-[11px] font-mono bg-muted/40 rounded p-2 overflow-auto whitespace-pre-wrap text-muted-foreground leading-relaxed">
                    {JSON.stringify(tool.parameters, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* View toggle */}
      <div className="flex items-center gap-1 self-end">
        {(["md", "raw"] as const).map(v => (
          <button
            key={v}
            onClick={() => setPromptView(v)}
            className={`px-2.5 py-1 text-xs rounded transition-colors border ${
              promptView === v
                ? "bg-background border-border font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {v === "md" ? "预览" : "原文"}
          </button>
        ))}
      </div>

      {promptView === "raw" ? (
        <pre className="flex-1 text-xs font-mono bg-muted/40 rounded-lg p-4 overflow-auto whitespace-pre-wrap leading-relaxed text-muted-foreground">
          {data ? data.system_prompt : (loading ? "加载中..." : "")}
        </pre>
      ) : (
        <div className="flex-1 overflow-auto space-y-2 pb-4">
          {data ? parseSections(data.system_prompt).map((section, i) => (
            <div key={i} className="rounded-lg border border-border/60 overflow-hidden">
              {section.tag && (
                <div className="px-4 py-1.5 bg-muted/40 border-b border-border/40 flex items-center gap-2">
                  <span className="text-xs font-mono text-muted-foreground">{section.tag}.md</span>
                </div>
              )}
              <div className="px-4 py-3 prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.content}</ReactMarkdown>
              </div>
            </div>
          )) : (
            <p className="text-muted-foreground italic text-sm">{loading ? "加载中..." : ""}</p>
          )}
        </div>
      )}
    </div>
  );
}


export function SettingsView({ models, initialTab = "general" }: SettingsViewProps) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<TabId>(initialTab);

  const handleTabChange = useCallback((tab: TabId) => {
    setActiveTab(tab);
    router.replace(`/settings/${tab}`, { scroll: false });
  }, [router]);
  const { theme, toggle: toggleTheme } = useTheme();

  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [channelExpanded, setChannelExpanded] = useState<string | null>("lark");
  const [channelForms, setChannelForms] = useState<Record<string, Record<string, string>>>({});
  const [channelSaving, setChannelSaving] = useState<string | null>(null);
  const [channelMessages, setChannelMessages] = useState<Record<string, { type: "success" | "error"; text: string }>>({});

  const [apiKeys, setApiKeys] = useState<APIKeyInfo[]>([]);
  const [apiKeyNewName, setApiKeyNewName] = useState("");
  const [apiKeyCreating, setApiKeyCreating] = useState(false);
  const [apiKeyJustCreated, setApiKeyJustCreated] = useState<APIKeyCreated | null>(null);

  useEffect(() => {
    if (activeTab === "api-keys") {
      fetchAPIKeys().then(setApiKeys).catch(() => {});
    }
  }, [activeTab]);

  const [agentForm, setAgentForm] = useState<AgentSettings>({
    workspace: "",
    agent_name: "",
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
    agent: "",
    tools: "",
    heartbeat: "",
  });

  const [providerForm, setProviderForm] = useState<ProviderSettings>({});

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    Promise.all([fetchAgentSettings(), fetchSystemSettings(), fetchProviderSettings(), fetchChannels()])
      .then(([agentData, sysData, providerData, channelData]) => {
        setAgentForm({
          ...agentData,
          heartbeat_enabled: agentData.heartbeat_enabled ?? true,
          heartbeat_interval_minutes: agentData.heartbeat_interval_minutes ?? 10,
        });
        setSysForm(sysData);
        setProviderForm(providerData);
        setChannels(channelData);
        const initial: Record<string, Record<string, string>> = {};
        for (const ch of channelData) initial[ch.id] = { ...ch.config };
        setChannelForms(initial);
      })
      .catch(() => setMessage({ type: "error", text: "加载设置失败" }))
      .finally(() => setLoading(false));
  }, []);

  const handleChannelSave = async (channelId: string) => {
    setChannelSaving(channelId);
    try {
      await patchChannel(channelId, channelForms[channelId] || {});
      const updated = await fetchChannels();
      setChannels(updated);
      setChannelMessages(prev => ({ ...prev, [channelId]: { type: "success", text: "已保存" } }));
      setTimeout(() => setChannelMessages(prev => { const n = { ...prev }; delete n[channelId]; return n; }), 3000);
    } catch {
      setChannelMessages(prev => ({ ...prev, [channelId]: { type: "error", text: "保存失败" } }));
    } finally {
      setChannelSaving(null);
    }
  };

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

  return (
    <div className="flex h-full w-full bg-background overflow-hidden">
      {/* Sidebar */}
      <div className="w-[200px] border-r bg-muted/30 flex flex-col">
        <div className="p-4 border-b">
          <h2 className="font-semibold">设置</h2>
        </div>
        <div className="flex-1 py-2 overflow-y-auto">
          {TAB_GROUPS.map(group => (
            <div key={group.group} className="mb-1">
              <div className="px-4 py-1.5 text-[10px] font-semibold text-muted-foreground/60 uppercase tracking-wider">
                {group.group}
              </div>
              {group.items.map(item => (
                <button
                  key={item.id}
                  onClick={() => handleTabChange(item.id)}
                  className={`w-full text-left px-4 py-2 text-sm transition-colors border-l-2 ${
                    activeTab === item.id
                      ? "border-primary text-foreground font-medium bg-muted/40"
                      : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/20"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-3xl flex flex-col gap-6 pb-6">
            
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
                          onChange={(e) => { const n = parseInt(e.target.value); if (!isNaN(n)) setAgentForm({ ...agentForm, heartbeat_interval_minutes: n }); }}
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
                            onChange={(e) => { const n = parseInt(e.target.value); if (!isNaN(n)) setAgentForm({ ...agentForm, max_tokens: n }); }}
                          />
                        </div>
                        <div className="flex-1 grid gap-1">
                          <label className="text-xs text-muted-foreground">Max Tool Iterations</label>
                          <Input
                            type="number"
                            value={agentForm.max_tool_iterations ?? 10}
                            onChange={(e) => { const n = parseInt(e.target.value); if (!isNaN(n)) setAgentForm({ ...agentForm, max_tool_iterations: n }); }}
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
                          onChange={(e) => { const n = parseInt(e.target.value); if (!isNaN(n)) setAgentForm({ ...agentForm, fast_max_length: n }); }}
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

            {activeTab === "channels" && (
              <div className="space-y-4">
                <h3 className="text-lg font-medium">渠道配置</h3>
                {channels.map(ch => {
                  const fields = CHANNEL_FIELDS[ch.id] || [];
                  const isOpen = channelExpanded === ch.id;
                  return (
                    <Card key={ch.id} className="border-border/60">
                      <CardHeader
                        className="cursor-pointer select-none"
                        onClick={() => setChannelExpanded(isOpen ? null : ch.id)}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            {isOpen ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                            <CardTitle className="text-base">{ch.name}</CardTitle>
                            <Badge variant={ch.enabled ? "default" : "secondary"} className="text-[10px]">
                              {ch.enabled ? "已连接" : "未配置"}
                            </Badge>
                          </div>
                        </div>
                        <CardDescription className="ml-7 text-xs">
                          {ch.id === "lark" ? "通过 WebSocket 长连接接收飞书消息，无需公网 IP" : ""}
                        </CardDescription>
                      </CardHeader>
                      {isOpen && (
                        <CardContent className="pt-0 ml-7">
                          <div className="space-y-3">
                            {fields.map(f => (
                              <div key={f.key} className="grid gap-1.5">
                                <label className="text-xs font-medium text-muted-foreground">{f.label}</label>
                                <Input
                                  type={f.secret ? "password" : "text"}
                                  placeholder={f.placeholder}
                                  value={channelForms[ch.id]?.[f.key] || ""}
                                  onChange={e => setChannelForms(prev => ({
                                    ...prev,
                                    [ch.id]: { ...prev[ch.id], [f.key]: e.target.value }
                                  }))}
                                />
                              </div>
                            ))}
                            <div className="flex items-center justify-between pt-2">
                              <span className="text-xs text-muted-foreground">
                                {channelMessages[ch.id] && (
                                  <span className={channelMessages[ch.id].type === "success" ? "text-green-500" : "text-red-500"}>
                                    {channelMessages[ch.id].text}
                                  </span>
                                )}
                              </span>
                              <Button size="sm" onClick={() => handleChannelSave(ch.id)} disabled={channelSaving === ch.id}>
                                {channelSaving === ch.id ? "保存中..." : "保存"}
                              </Button>
                            </div>
                          </div>
                        </CardContent>
                      )}
                    </Card>
                  );
                })}
                <Card className="border-dashed border-border/40 bg-muted/10">
                  <CardHeader>
                    <div className="flex items-center gap-3">
                      <ChevronRight className="h-4 w-4 text-muted-foreground/40" />
                      <CardTitle className="text-base text-muted-foreground/50">更多渠道即将支持...</CardTitle>
                    </div>
                    <CardDescription className="ml-7 text-xs text-muted-foreground/40">WeChat、Telegram、Slack 等</CardDescription>
                  </CardHeader>
                </Card>
              </div>
            )}

            {activeTab === "identity" && (
              <div className="h-full flex flex-col min-h-[500px]">
                <h3 className="text-lg font-medium mb-2">身份设定 (identity.md)</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  定义 Agent 的核心身份、角色扮演、说话语气等基本特征。
                </p>
                <MdEditor
                  value={sysForm.identity}
                  onChange={(v) => setSysForm({ ...sysForm, identity: v })}
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
                <MdEditor
                  value={sysForm.soul}
                  onChange={(v) => setSysForm({ ...sysForm, soul: v })}
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
                <MdEditor
                  value={sysForm.tools}
                  onChange={(v) => setSysForm({ ...sysForm, tools: v })}
                  placeholder="- shell: 执行 shell 命令..."
                />
              </div>
            )}

            {activeTab === "heartbeat" && (
              <div className="h-full flex flex-col min-h-[500px]">
                <h3 className="text-lg font-medium mb-2">心跳任务 (heartbeat.md)</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  每次心跳时执行的周期性任务，由 Agent 自主维护。文件内容完整传给 Agent 执行，支持 Markdown 格式。示例：检查今日日历并发送桌面通知。
                </p>
                <MdEditor
                  value={sysForm.heartbeat}
                  onChange={(v) => setSysForm({ ...sysForm, heartbeat: v })}
                  placeholder="# 在这里添加心跳任务..."
                />
              </div>
            )}

            {activeTab === "prompt-preview" && (
              <PromptPreview />
            )}

            {activeTab === "api-keys" && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-sm font-semibold mb-1">API Keys</h3>
                  <p className="text-xs text-muted-foreground mb-4">
                    用于 <code className="bg-muted px-1 rounded">/v1/chat/completions</code> 接口。
                    Key 以 <code className="bg-muted px-1 rounded">sk-ethan-</code> 开头，创建后只显示一次。
                  </p>

                  {/* Create new key */}
                  <div className="flex gap-2 mb-6">
                    <Input
                      placeholder="Key 名称（如 my-app）"
                      value={apiKeyNewName}
                      onChange={e => setApiKeyNewName(e.target.value)}
                      className="max-w-xs"
                    />
                    <Button
                      size="sm"
                      disabled={apiKeyCreating || !apiKeyNewName.trim()}
                      onClick={async () => {
                        setApiKeyCreating(true);
                        try {
                          const created = await createAPIKey(apiKeyNewName.trim());
                          setApiKeyJustCreated(created);
                          setApiKeyNewName("");
                          fetchAPIKeys().then(setApiKeys).catch(() => {});
                        } catch {
                          // ignore
                        } finally {
                          setApiKeyCreating(false);
                        }
                      }}
                    >
                      {apiKeyCreating ? "创建中..." : "创建"}
                    </Button>
                  </div>

                  {/* Show full key once after creation */}
                  {apiKeyJustCreated && (
                    <div className="mb-4 p-3 rounded-md bg-green-500/10 border border-green-500/30 text-sm">
                      <p className="font-medium text-green-600 mb-1">Key 已创建，请立即复制，之后无法再查看完整 Key：</p>
                      <code className="font-mono text-xs break-all select-all">{apiKeyJustCreated.key}</code>
                      <Button variant="ghost" size="sm" className="ml-2 text-xs" onClick={() => setApiKeyJustCreated(null)}>
                        我已复制
                      </Button>
                    </div>
                  )}

                  {/* Keys list */}
                  {apiKeys.length === 0 ? (
                    <p className="text-xs text-muted-foreground">暂无 API Key</p>
                  ) : (
                    <div className="space-y-2">
                      {apiKeys.map(k => (
                        <div key={k.id} className="flex items-center justify-between p-3 rounded-md border border-border bg-muted/20">
                          <div>
                            <div className="text-sm font-medium">{k.name}</div>
                            <div className="text-xs text-muted-foreground font-mono mt-0.5">{k.key_preview}</div>
                            <div className="text-xs text-muted-foreground mt-0.5">
                              创建于 {new Date(k.created_at * 1000).toLocaleString()}
                              {k.last_used_at && ` · 最近使用 ${new Date(k.last_used_at * 1000).toLocaleString()}`}
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-muted-foreground hover:text-destructive"
                            onClick={async () => {
                              await deleteAPIKey(k.id);
                              setApiKeys(prev => prev.filter(x => x.id !== k.id));
                            }}
                          >
                            删除
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="mt-6 p-3 rounded-md bg-muted/30 text-xs text-muted-foreground space-y-1">
                    <p className="font-medium text-foreground">调用示例</p>
                    <pre className="font-mono whitespace-pre-wrap">{`POST http://your-server:8900/v1/chat/completions
Authorization: Bearer sk-ethan-xxxx
Content-Type: application/json

{
  "model": "claude-sonnet-4-6",
  "messages": [{"role": "user", "content": "你好"}],
  "session_id": "optional-existing-session-id"
}`}</pre>
                    <p>返回中 <code>ethan.session_id</code> 字段可用于下次继续对话。</p>
                  </div>
                </div>
              </div>
            )}

          </div>
        </div>

        <div className="p-4 border-t bg-background flex items-center justify-between">
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
