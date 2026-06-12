"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { fetchAgentSettings, updateAgentSettings, AgentSettings, fetchSystemSettings, updateSystemSettings, SystemSettings } from "@/lib/api";

interface SettingsViewProps {
  models: { id: string; description: string }[];
}

export function SettingsView({ models }: SettingsViewProps) {
  const [form, setForm] = useState<AgentSettings>({
    agent_name: "",
    system_prompt: "",
    language: "zh",
    default_model: "",
  });
  const [sysForm, setSysForm] = useState<SystemSettings>({
    identity: "",
    soul: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    Promise.all([fetchAgentSettings(), fetchSystemSettings()])
      .then(([agentData, sysData]) => {
        setForm(agentData);
        setSysForm(sysData);
      })
      .catch(() => setMessage({ type: "error", text: "加载设置失败" }))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
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
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        <p>加载中...</p>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1">
      <div className="flex justify-center p-8">
        <div className="w-full max-w-lg bg-card border border-border rounded-2xl p-8 shadow-sm space-y-6">
          <h2 className="text-xl font-semibold">Agent 设置</h2>

          {/* Agent 名称 */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Agent 名称</label>
            <Input
              value={form.agent_name}
              onChange={(e) => setForm((prev) => ({ ...prev, agent_name: e.target.value }))}
              placeholder="例如：Ethan"
            />
          </div>

          {/* Identity (~/.ethan/system/identity.md) */}
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
          </div>

          {/* 默认语言 */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">默认语言</label>
            <select
              value={form.language}
              onChange={(e) => setForm((prev) => ({ ...prev, language: e.target.value }))}
              className="w-full text-sm bg-muted border border-border rounded-xl px-4 py-2.5 outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </div>

          {/* 默认模型 */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">默认模型</label>
            <select
              value={form.default_model}
              onChange={(e) => setForm((prev) => ({ ...prev, default_model: e.target.value }))}
              className="w-full text-sm bg-muted border border-border rounded-xl px-4 py-2.5 outline-none focus:ring-2 focus:ring-ring"
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.description || m.id}
                </option>
              ))}
            </select>
          </div>

          {/* Save button + message */}
          <div className="flex items-center gap-4 pt-2">
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "保存中..." : "保存"}
            </Button>
            {message && (
              <span
                className={`text-sm ${
                  message.type === "success" ? "text-green-500" : "text-destructive"
                }`}
              >
                {message.text}
              </span>
            )}
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}
