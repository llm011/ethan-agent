"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@ethan/shared/ui/button";
import { Input } from "@ethan/shared/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@ethan/shared/ui/card";
import { Badge } from "@ethan/shared/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@ethan/shared/ui/dialog";
import { RefreshCw, Plus, Trash2, Power } from "lucide-react";
import {
  fetchPlugins, addPlugin, removePlugin, restartServer,
  PluginInfo, PluginField,
} from "@/lib/api";
import { API_URL } from "@/lib/api-base";

export function PluginsTab() {
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [restartNeeded, setRestartNeeded] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [configDialog, setConfigDialog] = useState<PluginInfo | null>(null);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const loadPlugins = useCallback(async () => {
    try {
      const data = await fetchPlugins();
      setPlugins(data);
    } catch (e) {
      console.error("Failed to load plugins", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadPlugins(); }, [loadPlugins]);

  const showMessage = (type: "success" | "error", text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 3000);
  };

  const handleAdd = async (plugin: PluginInfo) => {
    const hasConfigFields = plugin.fields.some(f => !f.boolean && f.key !== "enabled");
    if (hasConfigFields) {
      const defaults: Record<string, string> = {};
      plugin.fields.forEach(f => {
        defaults[f.key] = plugin.current_values[f.key] || f.default || "";
      });
      setFieldValues(defaults);
      setConfigDialog(plugin);
      return;
    }
    setActionLoading(plugin.name);
    try {
      const res = await addPlugin(plugin.name);
      if (res.ok) {
        showMessage("success", res.message);
        if (res.restart_required) setRestartNeeded(true);
        await loadPlugins();
      } else {
        showMessage("error", res.message);
      }
    } catch {
      showMessage("error", "操作失败");
    } finally {
      setActionLoading(null);
    }
  };

  const handleConfigSubmit = async () => {
    if (!configDialog) return;
    setActionLoading(configDialog.name);
    setConfigDialog(null);
    try {
      const res = await addPlugin(configDialog.name, fieldValues);
      if (res.ok) {
        showMessage("success", res.message);
        if (res.restart_required) setRestartNeeded(true);
        await loadPlugins();
      } else {
        showMessage("error", res.message);
      }
    } catch {
      showMessage("error", "操作失败");
    } finally {
      setActionLoading(null);
    }
  };

  const handleRemove = async (plugin: PluginInfo) => {
    setActionLoading(plugin.name);
    try {
      const res = await removePlugin(plugin.name);
      if (res.ok) {
        showMessage("success", res.message);
        if (res.restart_required) setRestartNeeded(true);
        await loadPlugins();
      } else {
        showMessage("error", res.message);
      }
    } catch {
      showMessage("error", "操作失败");
    } finally {
      setActionLoading(null);
    }
  };

  const handleRestart = async () => {
    setRestarting(true);
    try {
      await restartServer();
    } catch {
      // expected - server will disconnect
    }
    // Poll health until server is back
    const poll = async () => {
      for (let i = 0; i < 30; i++) {
        await new Promise(r => setTimeout(r, 2000));
        try {
          const res = await fetch(`${API_URL}/health`);
          if (res.ok) {
            setRestarting(false);
            setRestartNeeded(false);
            showMessage("success", "服务已重启");
            await loadPlugins();
            return;
          }
        } catch {
          // still restarting
        }
      }
      setRestarting(false);
      showMessage("error", "重启超时，请手动检查服务状态");
    };
    poll();
  };

  const statusBadge = (status: string) => {
    switch (status) {
      case "enabled":
        return <Badge variant="default" className="bg-green-600">已启用</Badge>;
      case "disabled":
        return <Badge variant="secondary">未配置</Badge>;
      case "not_installed":
        return <Badge variant="secondary">未安装</Badge>;
      case "always":
        return <Badge variant="outline">始终可用</Badge>;
      default:
        return <Badge variant="secondary">{status}</Badge>;
    }
  };

  if (loading) {
    return <div className="text-sm text-muted-foreground">加载中...</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">插件管理</h3>
        <Button variant="ghost" size="sm" onClick={loadPlugins}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {restartNeeded && (
        <div className="flex items-center gap-3 rounded-md border border-yellow-300 bg-yellow-50 dark:border-yellow-700 dark:bg-yellow-900/20 p-3">
          <span className="text-sm text-yellow-800 dark:text-yellow-200">
            配置已更新，需要重启服务生效
          </span>
          <Button size="sm" onClick={handleRestart} disabled={restarting}>
            <Power className="h-3 w-3 mr-1" />
            {restarting ? "重启中..." : "重启服务"}
          </Button>
        </div>
      )}

      {message && (
        <div className={`text-sm px-3 py-2 rounded-md ${
          message.type === "success"
            ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300"
            : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300"
        }`}>
          {message.text}
        </div>
      )}

      <div className="grid gap-3">
        {plugins.map(plugin => (
          <Card key={plugin.name}>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <CardTitle className="text-base flex items-center gap-2">
                    {plugin.label || plugin.name}
                    {statusBadge(plugin.status)}
                  </CardTitle>
                  <CardDescription>{plugin.description}</CardDescription>
                </div>
                <div>
                  {plugin.category !== "builtin" && (
                    plugin.status === "enabled" ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRemove(plugin)}
                        disabled={actionLoading === plugin.name}
                      >
                        <Trash2 className="h-4 w-4 mr-1" />
                        移除
                      </Button>
                    ) : plugin.status !== "always" ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleAdd(plugin)}
                        disabled={actionLoading === plugin.name}
                      >
                        <Plus className="h-4 w-4 mr-1" />
                        启用
                      </Button>
                    ) : null
                  )}
                </div>
              </div>
            </CardHeader>
          </Card>
        ))}
      </div>

      {/* Config dialog for plugins with fields */}
      <Dialog open={!!configDialog} onOpenChange={(open) => !open && setConfigDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>配置插件: {configDialog?.label || configDialog?.name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {configDialog?.fields
              .filter(f => !f.boolean)
              .map(field => (
                <div key={field.key} className="space-y-2">
                  <label className="text-sm font-medium">{field.label}</label>
                  <Input
                    type={field.secret ? "password" : "text"}
                    placeholder={field.hint || field.default}
                    value={fieldValues[field.key] || ""}
                    onChange={(e) => setFieldValues(v => ({ ...v, [field.key]: e.target.value }))}
                  />
                  {field.hint && (
                    <p className="text-xs text-muted-foreground">{field.hint}</p>
                  )}
                </div>
              ))}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfigDialog(null)}>取消</Button>
            <Button onClick={handleConfigSubmit}>确认</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
