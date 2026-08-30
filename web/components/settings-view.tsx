"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@ethan/shared/ui/button";
import { Input } from "@ethan/shared/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ethan/shared/ui/select";
import { Check, ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { MdEditor } from "@ethan/shared/components/md-editor";
import {
  fetchAgentSettings, updateAgentSettings, AgentSettings,
  fetchSystemSettings, updateSystemSettings, SystemSettings,
  fetchProviderSettings, updateProviderSettings, ProviderSettings, ProviderPreset,
  fetchProviderPresets, deleteProvider,
  fetchChannels, patchChannel, ChannelInfo,
  fetchAPIKeys, createAPIKey, deleteAPIKey, APIKeyInfo, APIKeyCreated,
  fetchModels, addModel, addModelsBatch, deleteModel, deleteModelsBatch, discoverModels, ModelEntry,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@ethan/shared/ui/card";
import { Badge } from "@ethan/shared/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@ethan/shared/ui/dialog";
import { useTheme } from "@/components/chat/use-theme";
import { THEMES } from "@/components/chat/themes";
import { ThemeSwatch } from "@ethan/shared/components/theme-swatch";
import { PromptPreview } from "./settings/prompt-preview";
import { ProfileEditor } from "./settings/profile-editor";
import { FastRulesTab } from "./settings/fast-rules-tab";
import { PluginsTab } from "./settings/plugins-tab";
import { ToolTiersView } from "./tool-tiers-view";
import { ConfirmDialog } from "./confirm-dialog";

interface SettingsViewProps {
  models: { id: string; description: string }[];
  initialTab?: TabId;
}

type TabId = "general" | "fast-rules" | "providers" | "channels" | "plugins" | "identity" | "soul" | "tools" | "heartbeat" | "profile" | "prompt-preview" | "api-keys" | "tool-tiers";

const TAB_GROUPS = [
  {
    group: "基础配置",
    items: [
      { id: "general" as TabId, label: "通用" },
      { id: "fast-rules" as TabId, label: "快捷路由" },
      { id: "providers" as TabId, label: "模型 provider" },
      { id: "channels" as TabId, label: "渠道" },
      { id: "plugins" as TabId, label: "插件" },
    ],
  },
  {
    group: "个人画像",
    items: [
      { id: "profile" as TabId, label: "我的画像" },
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
      { id: "tool-tiers" as TabId, label: "模式工具集" },
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

export function SettingsView({ models, initialTab = "general" }: SettingsViewProps) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<TabId>(initialTab);
  const handleTabChange = useCallback((tab: TabId) => {
    setActiveTab(tab);
    router.replace(`/settings/${tab}`, { scroll: false });
  }, [router]);
  const { theme, setTheme } = useTheme();

  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  // 模型管理
  const [modelList, setModelList] = useState<ModelEntry[]>([]);
  const [discovered, setDiscovered] = useState<(ModelEntry & { exists?: boolean })[]>([]);
  const [discoverProvider, setDiscoverProvider] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [discoverOpen, setDiscoverOpen] = useState(false); // 拉取弹窗开关
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set()); // 弹窗里勾选的 model id
  const [discoverSearch, setDiscoverSearch] = useState(""); // 弹窗搜索词
  const [newModel, setNewModel] = useState<ModelEntry>({ id: "", provider: "openai_compat", description: "", alias: [], vision: true });
  // 批量删除/添加模型
  const [selectedModelKeys, setSelectedModelKeys] = useState<Set<string>>(new Set()); // 勾选的 "provider/id"
  const [batchAddOpen, setBatchAddOpen] = useState(false);
  const [batchAddProvider, setBatchAddProvider] = useState("");
  const [batchAddText, setBatchAddText] = useState("");
  const [batchAdding, setBatchAdding] = useState(false);
  const [batchDeleting, setBatchDeleting] = useState(false);
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
    lite_model: "",
    heartbeat_enabled: true,
    heartbeat_interval_minutes: 10,
    heartbeat_model: "",
    schedule_model: "",
    proxy: "",
    max_tokens: 4096,
    max_tool_iterations: 100,
  });
  
  const [sysForm, setSysForm] = useState<SystemSettings>({
    identity: "",
    soul: "",
    agent: "",
    tools: "",
    heartbeat: "",
  });

  const [providerForm, setProviderForm] = useState<ProviderSettings>({});
  const [providerPresets, setProviderPresets] = useState<ProviderPreset[]>([]);
  const [addProviderOpen, setAddProviderOpen] = useState(false);
  const [newProvider, setNewProvider] = useState<{ key: string; type: string; base_url: string; api_key: string; disable_prompt_cache: boolean }>({ key: "", type: "openai_compat", base_url: "", api_key: "", disable_prompt_cache: false });
  const [deleteProviderKey, setDeleteProviderKey] = useState<string | null>(null);
  const [providerMsg, setProviderMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    Promise.all([fetchAgentSettings(), fetchSystemSettings(), fetchProviderSettings(), fetchChannels(), fetchModels(), fetchProviderPresets()])
      .then(([agentData, sysData, providerData, channelData, models, presetsData]) => {
        setAgentForm({
          ...agentData,
          heartbeat_enabled: agentData.heartbeat_enabled ?? true,
          heartbeat_interval_minutes: agentData.heartbeat_interval_minutes ?? 10,
        });
        setSysForm(sysData);
        setProviderForm(providerData);
        setChannels(channelData);
        setModelList(models);
        setProviderPresets(presetsData.presets);
        const initial: Record<string, Record<string, string>> = {};
        for (const ch of channelData) initial[ch.id] = { ...ch.config };
        setChannelForms(initial);
        // 默认选中第一个 provider 做 discover
        if (models.length > 0) setDiscoverProvider(models[0].provider);
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

  const showProviderMsg = (type: "success" | "error", text: string) => {
    setProviderMsg({ type, text });
    setTimeout(() => setProviderMsg(null), 3000);
  };

  // 添加 provider：实时调用 PATCH 创建单个 provider（不再依赖底部「保存设置」）
  const handleAddProvider = async () => {
    const key = newProvider.key.trim();
    if (!key) { showProviderMsg("error", "Provider key 不能为空"); return; }
    if (key in providerForm) { showProviderMsg("error", `Provider '${key}' 已存在`); return; }
    try {
      await updateProviderSettings({
        [key]: {
          api_key: newProvider.api_key,
          base_url: newProvider.base_url || null,
          type: newProvider.type,
          disable_prompt_cache: newProvider.disable_prompt_cache,
        },
      });
      const refreshed = await fetchProviderSettings();
      setProviderForm(refreshed);
      setAddProviderOpen(false);
      setNewProvider({ key: "", type: "openai_compat", base_url: "", api_key: "", disable_prompt_cache: false });
      showProviderMsg("success", `Provider '${key}' 已添加`);
    } catch (e) {
      console.error("添加 provider 失败", e);
      showProviderMsg("error", "添加失败，请重试");
    }
  };

  // 批量删除勾选的模型（key 格式 "provider/id"，id 本身可能含 "/"，用第一个 "/" 切分）
  const handleDeleteModelSelected = async () => {
    if (selectedModelKeys.size === 0) return;
    setBatchDeleting(true);
    try {
      const items = [...selectedModelKeys].map((k) => {
        const idx = k.indexOf("/");
        return { provider: k.slice(0, idx), id: k.slice(idx + 1) };
      });
      const r = await deleteModelsBatch(items);
      if (r.ok) {
        setModelList(await fetchModels());
        setSelectedModelKeys(new Set());
        setMessage({ type: "success", text: `已删除 ${r.deleted} 个模型` });
        setTimeout(() => setMessage(null), 3000);
      } else {
        setMessage({ type: "error", text: r.error || "批量删除失败" });
      }
    } finally {
      setBatchDeleting(false);
    }
  };

  // 批量添加模型（textarea 每行一个 model id）
  const handleBatchAdd = async () => {
    const ids = batchAddText.split("\n").map((s) => s.trim()).filter(Boolean);
    if (ids.length === 0 || !batchAddProvider) return;
    setBatchAdding(true);
    try {
      const r = await addModelsBatch(ids.map((id) => ({ id, provider: batchAddProvider, description: id, alias: [], vision: true })));
      if (r.ok) {
        setModelList(await fetchModels());
        setBatchAddOpen(false);
        setBatchAddText("");
        const skippedCount = r.skipped?.length ?? 0;
        setMessage({ type: "success", text: `已添加 ${r.added} 个模型${skippedCount > 0 ? `，跳过 ${skippedCount} 个重复` : ""}` });
        setTimeout(() => setMessage(null), 3000);
      } else {
        setMessage({ type: "error", text: r.error || "批量添加失败" });
      }
    } finally {
      setBatchAdding(false);
    }
  };

  // 从预设填充添加表单
  const applyPresetToForm = (preset: ProviderPreset) => {
    setNewProvider({
      key: preset.key,
      type: preset.type,
      base_url: preset.base_url,
      api_key: "",
      disable_prompt_cache: preset.disable_prompt_cache ?? false,
    });
  };

  // 删除 provider：实时调 API，成功后刷新 provider 和模型列表（引用该 provider 的模型已被级联删除）
  const handleDeleteProvider = async () => {
    if (!deleteProviderKey) return;
    const key = deleteProviderKey;
    try {
      await deleteProvider(key);
      const refreshed = await fetchProviderSettings();
      setProviderForm(refreshed);
      setModelList(await fetchModels());
      setSelectedModelKeys(new Set());
      showProviderMsg("success", `Provider '${key}' 已删除`);
    } catch (e) {
      console.error("删除 provider 失败", e);
      showProviderMsg("error", "删除失败，请重试");
    } finally {
      setDeleteProviderKey(null);
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
                          {modelList.map((m) => (
                            <SelectItem key={m.id} value={m.id}>
                              {m.description || m.id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">轻量模型（可选）</label>
                      <Select
                        value={agentForm.lite_model}
                        onValueChange={(val) => setAgentForm({ ...agentForm, lite_model: val || "" })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="留空则按主模型推断" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="">留空（自动推断）</SelectItem>
                          {modelList.map((m) => (
                            <SelectItem key={m.id} value={m.id}>
                              {m.description || m.id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <p className="text-xs text-muted-foreground">用于记忆压缩、智能标题、skill 自生成等后台任务，选个便宜快的。</p>
                    </div>

                    {/* 模型列表管理 */}
                    <div className="grid gap-2">
                      <div className="flex items-center justify-between">
                        <label className="text-sm font-medium">模型列表</label>
                        <div className="flex items-center gap-2">
                          {selectedModelKeys.size > 0 && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="text-red-500 hover:text-red-600"
                              disabled={batchDeleting}
                              onClick={handleDeleteModelSelected}
                            >{batchDeleting ? "删除中..." : `删除所选（${selectedModelKeys.size}）`}</Button>
                          )}
                          <span className="text-xs text-muted-foreground">{modelList.length} 个</span>
                        </div>
                      </div>
                      <div className="rounded-md border border-border/60 divide-y divide-border/40">
                        {modelList.length > 0 && (
                          <label className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground cursor-pointer bg-muted/20">
                            <input
                              type="checkbox"
                              className="accent-primary"
                              checked={modelList.length > 0 && selectedModelKeys.size === modelList.length}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSelectedModelKeys(new Set(modelList.map((m) => `${m.provider}/${m.id}`)));
                                } else {
                                  setSelectedModelKeys(new Set());
                                }
                              }}
                            />
                            全选
                          </label>
                        )}
                        {modelList.map((m) => {
                          const key = `${m.provider}/${m.id}`;
                          return (
                            <div key={key} className="flex items-center gap-2 px-3 py-2 text-sm">
                              <input
                                type="checkbox"
                                className="accent-primary shrink-0"
                                checked={selectedModelKeys.has(key)}
                                onChange={(e) => {
                                  setSelectedModelKeys((prev) => {
                                    const next = new Set(prev);
                                    if (e.target.checked) next.add(key);
                                    else next.delete(key);
                                    return next;
                                  });
                                }}
                              />
                              <span className="font-mono text-xs text-muted-foreground shrink-0">{m.provider}</span>
                              <span className="font-mono">{m.id}</span>
                              {m.description && m.description !== m.id && (
                                <span className="text-xs text-muted-foreground truncate">· {m.description}</span>
                              )}
                              <button
                                className="ml-auto text-xs text-muted-foreground hover:text-red-400 shrink-0"
                                onClick={async () => {
                                  const r = await deleteModel(m.provider, m.id);
                                  if (r.ok) {
                                    setModelList(await fetchModels());
                                    setSelectedModelKeys((prev) => { const n = new Set(prev); n.delete(key); return n; });
                                  }
                                  else setMessage({ type: "error", text: r.error || "删除失败" });
                                }}
                              >删除</button>
                            </div>
                          );
                        })}
                        {modelList.length === 0 && (
                          <div className="px-3 py-3 text-sm text-muted-foreground">暂无模型</div>
                        )}
                      </div>

                      {/* 手工添加 */}
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        <Input
                          className="flex-1 min-w-[120px]"
                          placeholder="model id（如 gemini-3-flash）"
                          value={newModel.id}
                          onChange={(e) => setNewModel({ ...newModel, id: e.target.value })}
                        />
                        <Select
                          value={newModel.provider}
                          onValueChange={(v) => setNewModel({ ...newModel, provider: v || "" })}
                        >
                          <SelectTrigger className="w-[140px]"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {Object.keys(providerForm).map((p) => (
                              <SelectItem key={p} value={p}>{p}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button
                          variant="outline"
                          disabled={!newModel.id.trim()}
                          onClick={async () => {
                            const r = await addModel({ ...newModel, id: newModel.id.trim() });
                            if (r.ok) { setModelList(await fetchModels()); setNewModel({ ...newModel, id: "" }); }
                            else setMessage({ type: "error", text: r.error || "添加失败" });
                          }}
                        >添加</Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-muted-foreground"
                          onClick={() => {
                            setNewProvider({ key: "", type: "openai_compat", base_url: "", api_key: "", disable_prompt_cache: false });
                            setAddProviderOpen(true);
                          }}
                        ><Plus className="h-3.5 w-3.5" /> Provider</Button>
                      </div>

                      {/* provider 模型发现 */}
                      <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-border/40">
                        <Select value={discoverProvider} onValueChange={(v) => setDiscoverProvider(v || "")}>
                          <SelectTrigger className="w-[160px]"><SelectValue placeholder="选 provider" /></SelectTrigger>
                          <SelectContent>
                            {Object.keys(providerForm).map((p) => (
                              <SelectItem key={p} value={p}>{p}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button
                          variant="outline"
                          disabled={!discoverProvider || discovering}
                          onClick={async () => {
                            if (!discoverProvider) return;
                            setDiscovering(true);
                            setDiscoverSearch("");
                            setSelectedIds(new Set());
                            try {
                              const r = await discoverModels(discoverProvider);
                              if (r.ok && r.models) {
                                setDiscovered(r.models);
                                setDiscoverOpen(true);
                              } else {
                                setMessage({ type: "error", text: r.error || "拉取失败" });
                              }
                            } finally { setDiscovering(false); }
                          }}
                        >{discovering ? "拉取中…" : "从 provider 拉取候选"}</Button>
                        <Button
                          variant="outline"
                          onClick={() => {
                            setBatchAddProvider(discoverProvider || Object.keys(providerForm)[0] || "");
                            setBatchAddText("");
                            setBatchAddOpen(true);
                          }}
                        >批量添加</Button>
                      </div>

                      {/* 拉取结果弹窗：搜索 + 勾选 + 批量加入 */}
                      <Dialog open={discoverOpen} onOpenChange={setDiscoverOpen}>
                        <DialogContent className="max-w-lg">
                          <DialogHeader>
                            <DialogTitle>从 {discoverProvider} 拉取的模型</DialogTitle>
                            <DialogDescription>
                              勾选要加入的模型，点「确认加入」。{discovered.length} 个候选。
                            </DialogDescription>
                          </DialogHeader>
                          <Input
                            placeholder="搜索 model id…"
                            value={discoverSearch}
                            onChange={(e) => setDiscoverSearch(e.target.value)}
                            className="mb-2"
                          />
                          <div className="rounded-md border border-border/60 max-h-80 overflow-y-auto divide-y divide-border/30">
                            {discovered
                              .filter((m) => m.id.toLowerCase().includes(discoverSearch.toLowerCase()))
                              .map((m) => {
                                const checked = selectedIds.has(m.id);
                                return (
                                  <label key={m.id} className={`flex items-center gap-2 px-3 py-2 text-sm cursor-pointer ${m.exists ? "opacity-50" : "hover:bg-muted/40"}`}>
                                    <input
                                      type="checkbox"
                                      className="accent-primary"
                                      disabled={m.exists}
                                      checked={checked}
                                      onChange={(e) => {
                                        setSelectedIds((prev) => {
                                          const next = new Set(prev);
                                          if (e.target.checked) next.add(m.id);
                                          else next.delete(m.id);
                                          return next;
                                        });
                                      }}
                                    />
                                    <span className="font-mono text-xs">{m.id}</span>
                                    {m.exists && <span className="text-[10px] text-muted-foreground">已添加</span>}
                                  </label>
                                );
                              })}
                            {discovered.filter((m) => m.id.toLowerCase().includes(discoverSearch.toLowerCase())).length === 0 && (
                              <div className="px-3 py-4 text-sm text-muted-foreground text-center">无匹配结果</div>
                            )}
                          </div>
                          <DialogFooter>
                            <Button variant="outline" onClick={() => setDiscoverOpen(false)}>取消</Button>
                            <Button
                              disabled={selectedIds.size === 0}
                              onClick={async () => {
                                const toAdd = discovered.filter((m) => selectedIds.has(m.id) && !m.exists);
                                if (toAdd.length === 0) { setDiscoverOpen(false); return; }
                                const r = await addModelsBatch(toAdd.map((m) => ({ id: m.id, provider: m.provider, description: m.description, alias: [], vision: true })));
                                if (r.ok) {
                                  setModelList(await fetchModels());
                                  setSelectedIds(new Set());
                                  setDiscoverOpen(false);
                                  setMessage({ type: "success", text: `已加入 ${r.added} 个模型` });
                                  setTimeout(() => setMessage(null), 3000);
                                } else {
                                  setMessage({ type: "error", text: r.error || "批量加入失败" });
                                }
                              }}
                            >确认加入{selectedIds.size > 0 ? `（${selectedIds.size}）` : ""}</Button>
                          </DialogFooter>
                        </DialogContent>
                      </Dialog>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">外观主题</label>
                      <div className="flex flex-wrap gap-2">
                        {THEMES.map((t) => (
                          <button
                            key={t.id}
                            type="button"
                            onClick={() => setTheme(t.id)}
                            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors ${
                              theme === t.id
                                ? "border-primary bg-primary/10 text-foreground"
                                : "border-border text-muted-foreground hover:bg-muted"
                            }`}
                          >
                            <ThemeSwatch colors={t.swatch} />
                            {t.label}
                            {theme === t.id && <Check className="h-3.5 w-3.5 text-primary" />}
                          </button>
                        ))}
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
                      <label className="text-sm font-medium">心跳任务模型</label>
                      <Select
                        value={agentForm.heartbeat_model ?? ""}
                        onValueChange={(val) => setAgentForm({ ...agentForm, heartbeat_model: val || "" })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="留空则跟随默认模型" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="">留空（跟随默认模型）</SelectItem>
                          {modelList.map((m) => (
                            <SelectItem key={m.id} value={m.id}>
                              {m.description || m.id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="grid gap-2">
                      <label className="text-sm font-medium">定时任务模型</label>
                      <Select
                        value={agentForm.schedule_model ?? ""}
                        onValueChange={(val) => setAgentForm({ ...agentForm, schedule_model: val || "" })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="留空则跟随默认模型" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="">留空（跟随默认模型）</SelectItem>
                          {modelList.map((m) => (
                            <SelectItem key={m.id} value={m.id}>
                              {m.description || m.id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
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
                  </div>
                </div>
              </div>
            )}

            {activeTab === "fast-rules" && <FastRulesTab />}

            {activeTab === "providers" && (
              <div className="space-y-6">
                <div>
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-medium">模型 provider</h3>
                    <Button variant="outline" size="sm" onClick={() => setAddProviderOpen(true)}>
                      <Plus className="h-4 w-4 mr-1" />添加 Provider
                    </Button>
                  </div>
                  <div className="space-y-6">
                    {Object.entries(providerForm).map(([key, config]) => (
                      <div key={key} className="border p-4 rounded-md space-y-4">
                        <div className="flex items-center justify-between">
                          <h4 className="font-medium text-sm capitalize">{key}</h4>
                          <button
                            className="text-xs text-muted-foreground hover:text-red-500 flex items-center gap-1"
                            onClick={() => setDeleteProviderKey(key)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />删除
                          </button>
                        </div>
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
                          <div className="grid gap-2">
                            <label className="text-xs text-muted-foreground">协议类型</label>
                            <Select
                              value={config.type || "openai_compat"}
                              onValueChange={(val) => setProviderForm({
                                ...providerForm,
                                [key]: { ...config, type: val || "openai_compat" }
                              })}
                            >
                              <SelectTrigger>
                                <SelectValue placeholder="选择协议" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="anthropic">anthropic</SelectItem>
                                <SelectItem value="openai_compat">openai_compat</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          <label className="flex items-center gap-2 text-sm cursor-pointer pt-1">
                            <input
                              type="checkbox"
                              className="w-4 h-4"
                              checked={config.disable_prompt_cache ?? false}
                              onChange={(e) => setProviderForm({
                                ...providerForm,
                                [key]: { ...config, disable_prompt_cache: e.target.checked }
                              })}
                            />
                            禁用 Prompt Cache
                            <span className="text-xs text-muted-foreground">（第三方网关不支持 cache_control 时开启）</span>
                          </label>
                        </div>
                      </div>
                    ))}
                    {Object.keys(providerForm).length === 0 && (
                      <div className="text-sm text-muted-foreground text-center py-8 border border-dashed rounded-md">
                        暂无 provider，点击右上角「添加 Provider」开始配置
                      </div>
                    )}
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

            {activeTab === "profile" && (
              <ProfileEditor />
            )}

            {activeTab === "prompt-preview" && (
              <PromptPreview />
            )}

            {activeTab === "tool-tiers" && (
              <div className="h-[calc(88vh-200px)] min-h-[400px]">
                <ToolTiersView embedded />
              </div>
            )}

            {activeTab === "plugins" && <PluginsTab />}

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
  "model": "claude-sonnet-4.6",
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

        {/* 添加 Provider 对话框（通用/模型 provider 两处入口共用）：即时落盘，无需点「保存设置」 */}
        <Dialog open={addProviderOpen} onOpenChange={setAddProviderOpen}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>添加 Provider</DialogTitle>
              <DialogDescription>从内置预设快速填充，或手动填写。保存后立即生效。</DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              {providerPresets.length > 0 && (
                <>
                  <div className="text-xs font-medium text-muted-foreground">从预设填充</div>
                  <div className="rounded-md border divide-y max-h-40 overflow-y-auto">
                    {providerPresets
                      .filter(p => !providerForm[p.key])
                      .map(preset => (
                        <button
                          key={preset.key}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-muted/40 flex items-center justify-between"
                          onClick={() => applyPresetToForm(preset)}
                        >
                          <div>
                            <div className="font-mono font-medium">{preset.key}</div>
                            <div className="text-xs text-muted-foreground">{preset.description}</div>
                          </div>
                          <Plus className="h-4 w-4 text-muted-foreground" />
                        </button>
                      ))}
                    {providerPresets.every(p => providerForm[p.key]) && (
                      <div className="px-3 py-3 text-xs text-muted-foreground text-center">所有预设已添加</div>
                    )}
                  </div>
                </>
              )}
              <div className="grid gap-2">
                <label className="text-xs text-muted-foreground">Provider Key</label>
                <Input
                  placeholder="如 openai、deepseek"
                  value={newProvider.key}
                  onChange={(e) => setNewProvider({ ...newProvider, key: e.target.value })}
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="grid gap-2">
                  <label className="text-xs text-muted-foreground">协议类型</label>
                  <Select value={newProvider.type} onValueChange={(v) => setNewProvider({ ...newProvider, type: v || "openai_compat" })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="anthropic">anthropic</SelectItem>
                      <SelectItem value="openai_compat">openai_compat</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <label className="text-xs text-muted-foreground">禁用 Prompt Cache</label>
                  <Select value={newProvider.disable_prompt_cache ? "true" : "false"} onValueChange={(v) => setNewProvider({ ...newProvider, disable_prompt_cache: v === "true" })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="false">否</SelectItem>
                      <SelectItem value="true">是</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid gap-2">
                <label className="text-xs text-muted-foreground">Base URL</label>
                <Input
                  value={newProvider.base_url}
                  onChange={(e) => setNewProvider({ ...newProvider, base_url: e.target.value })}
                  placeholder="https://api.example.com/v1"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-xs text-muted-foreground">API Key</label>
                <Input
                  type="password"
                  value={newProvider.api_key}
                  onChange={(e) => setNewProvider({ ...newProvider, api_key: e.target.value })}
                  placeholder="sk-..."
                />
              </div>
              {providerMsg && (
                <div className={`text-xs ${providerMsg.type === "success" ? "text-green-500" : "text-red-500"}`}>{providerMsg.text}</div>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setAddProviderOpen(false)}>取消</Button>
              <Button onClick={handleAddProvider} disabled={!newProvider.key.trim()}>添加</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* 批量添加模型对话框：每行一个 model id */}
        <Dialog open={batchAddOpen} onOpenChange={setBatchAddOpen}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>批量添加模型</DialogTitle>
              <DialogDescription>每行一个 model id，重复的会自动跳过。</DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <div className="grid gap-2">
                <label className="text-xs text-muted-foreground">所属 Provider</label>
                <Select value={batchAddProvider} onValueChange={(v) => setBatchAddProvider(v || "")}>
                  <SelectTrigger><SelectValue placeholder="选择 provider" /></SelectTrigger>
                  <SelectContent>
                    {Object.keys(providerForm).map((p) => (
                      <SelectItem key={p} value={p}>{p}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <label className="text-xs text-muted-foreground">Model ID 列表</label>
                <textarea
                  className="min-h-[140px] rounded-md border border-border/60 bg-transparent px-3 py-2 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                  placeholder={"gpt-5.2\ngpt-5.2-mini\ndeepseek-ai/DeepSeek-V3"}
                  value={batchAddText}
                  onChange={(e) => setBatchAddText(e.target.value)}
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setBatchAddOpen(false)}>取消</Button>
              <Button onClick={handleBatchAdd} disabled={batchAdding || !batchAddProvider || !batchAddText.trim()}>
                {batchAdding ? "添加中..." : "添加"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* 删除 Provider 确认 */}
        <ConfirmDialog
          open={deleteProviderKey !== null}
          title="删除 Provider"
          description={`确定删除 provider「${deleteProviderKey}」？引用该 provider 的模型也会一并移除，此操作不可撤销。`}
          confirmLabel="删除"
          onCancel={() => setDeleteProviderKey(null)}
          onConfirm={handleDeleteProvider}
        />

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
