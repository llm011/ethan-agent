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
  fetchProviderSettings, updateProviderSettings, ProviderSettings
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

type TabType = "general" | "providers" | "identity" | "soul" | "format";

export function SettingsView({ models }: SettingsViewProps) {
  const [activeTab, setActiveTab] = useState<TabType>("general");
  const { theme, toggle: toggleTheme } = useTheme();
  
  const [agentForm, setAgentForm] = useState<AgentSettings>({
    workspace: "",
    agent_name: "",
    system_prompt: "",
    language: "zh",
    default_model: "",
  });
  
  const [sysForm, setSysForm] = useState<SystemSettings>({
    identity: "",
    soul: "",
    format: "",
  });

  const [providerForm, setProviderForm] = useState<ProviderSettings>({});

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    Promise.all([fetchAgentSettings(), fetchSystemSettings(), fetchProviderSettings()])
      .then(([agentData, sysData, providerData]) => {
        setAgentForm(agentData);
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
    { id: "format", label: "输出规范 (Format)" },
  ];

  return (
    <div className="flex h-full w-full bg-background overflow-hidden border rounded-md">
      {/* Sidebar */}
      <div className="w-[200px] border-r bg-muted/30 flex flex-col">
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

            {activeTab === "format" && (
              <div className="h-full flex flex-col min-h-[500px]">
                <h3 className="text-lg font-medium mb-2">输出规范 (format.md)</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  定义 Agent 回复的具体格式要求（如 Markdown、JSON、字数限制等）。
                </p>
                <Textarea
                  className="flex-1 font-mono text-sm resize-none"
                  value={sysForm.format}
                  onChange={(e) => setSysForm({ ...sysForm, format: e.target.value })}
                  placeholder="Output rules..."
                />
              </div>
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
