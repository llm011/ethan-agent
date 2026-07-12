"use client";

import { useEffect, useState, useRef } from "react";
import { ChannelInfo, fetchChannels, patchChannel, LarkDepsStatus, fetchLarkDepsStatus, installLarkDeps } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Loader2 } from "lucide-react";

// 每个渠道的字段定义（用于渲染表单）
const CHANNEL_FIELDS: Record<string, { key: string; label: string; secret?: boolean; placeholder?: string }[]> = {
  lark: [
    { key: "app_id", label: "App ID", placeholder: "cli_xxx" },
    { key: "app_secret", label: "App Secret", secret: true, placeholder: "xxxxxxxx" },
  ],
};

export function ChannelsView() {
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [expanded, setExpanded] = useState<string | null>("lark");
  const [forms, setForms] = useState<Record<string, Record<string, string>>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, { type: "success" | "error"; text: string }>>({});
  const [depsStatus, setDepsStatus] = useState<LarkDepsStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = () => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const s = await fetchLarkDepsStatus();
        setDepsStatus(s);
        if (!s.installing) stopPolling();
      } catch { /* ignore */ }
    }, 2000);
  };

  useEffect(() => {
    fetchChannels().then(data => {
      setChannels(data);
      const initial: Record<string, Record<string, string>> = {};
      for (const ch of data) initial[ch.id] = { ...ch.config };
      setForms(initial);
    }).catch(() => {});
    // 首次加载也拉一次依赖状态
    fetchLarkDepsStatus().then(setDepsStatus).catch(() => {});
    return () => stopPolling();
  }, []);

  const handleSave = async (channelId: string) => {
    setSaving(channelId);
    try {
      await patchChannel(channelId, forms[channelId] || {});
      const updated = await fetchChannels();
      setChannels(updated);
      setMessages(prev => ({ ...prev, [channelId]: { type: "success", text: "已保存，依赖正在后台安装…" } }));
      // 启动轮询依赖状态
      if (channelId === "lark") startPolling();
      setTimeout(() => setMessages(prev => { const n = { ...prev }; delete n[channelId]; return n; }), 4000);
    } catch {
      setMessages(prev => ({ ...prev, [channelId]: { type: "error", text: "保存失败" } }));
    } finally {
      setSaving(null);
    }
  };

  const handleRetryInstall = async () => {
    try {
      await installLarkDeps();
      startPolling();
    } catch {
      setMessages(prev => ({ ...prev, lark: { type: "error", text: "触发安装失败" } }));
    }
  };

  return (
    <div className="flex flex-col h-full bg-background text-foreground">
      <header className="h-12 border-b border-border flex items-center px-4 shrink-0">
        <h1 className="font-semibold text-lg">渠道 (Channels)</h1>
      </header>
      <ScrollArea className="flex-1 p-6">
        <div className="max-w-2xl mx-auto space-y-4">
          {channels.map(ch => {
            const fields = CHANNEL_FIELDS[ch.id] || [];
            const isOpen = expanded === ch.id;
            return (
              <Card key={ch.id} className="border-border/60">
                <CardHeader
                  className="cursor-pointer select-none"
                  onClick={() => setExpanded(isOpen ? null : ch.id)}
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
                            value={forms[ch.id]?.[f.key] || ""}
                            onChange={e => setForms(prev => ({
                              ...prev,
                              [ch.id]: { ...prev[ch.id], [f.key]: e.target.value }
                            }))}
                          />
                        </div>
                      ))}
                      <div className="flex items-center justify-between pt-2">
                        <span className="text-xs text-muted-foreground">
                          {messages[ch.id] && (
                            <span className={messages[ch.id].type === "success" ? "text-green-500" : "text-red-500"}>
                              {messages[ch.id].text}
                            </span>
                          )}
                        </span>
                        <Button size="sm" onClick={() => handleSave(ch.id)} disabled={saving === ch.id}>
                          {saving === ch.id ? "保存中..." : "保存"}
                        </Button>
                      </div>

                      {/* 飞书依赖状态展示 */}
                      {ch.id === "lark" && depsStatus && (
                        <div className="mt-3 pt-3 border-t border-border/40 space-y-2">
                          <div className="text-xs font-medium text-muted-foreground">依赖就绪状态</div>
                          <div className="space-y-1.5 text-xs">
                            <DepsRow
                              label="lark-oapi (Python 包)"
                              ok={depsStatus.lark_oapi_installed}
                              installing={depsStatus.installing && !depsStatus.lark_oapi_installed}
                            />
                            <DepsRow
                              label="lark-cli (二进制)"
                              ok={depsStatus.lark_cli_installed}
                              installing={depsStatus.installing && !depsStatus.lark_cli_installed}
                            />
                            <DepsRow
                              label="lark-cli app 同步"
                              ok={depsStatus.lark_cli_app_matches}
                              installing={depsStatus.installing && !depsStatus.lark_cli_app_matches}
                            />
                          </div>
                          {depsStatus.installing && (
                            <div className="flex items-center gap-2 text-xs text-yellow-600">
                              <Loader2 className="h-3 w-3 animate-spin" />
                              正在后台安装…（brew / pip 可能需要 1-3 分钟）
                            </div>
                          )}
                          {!depsStatus.installing && depsStatus.last_error && (
                            <div className="text-xs text-red-500">
                              <div className="font-medium">部分依赖未就绪：</div>
                              <pre className="mt-1 whitespace-pre-wrap text-[10px] text-red-400 max-h-24 overflow-auto">
                                {depsStatus.last_error}
                              </pre>
                              <Button size="sm" variant="outline" className="mt-2 h-6 text-xs" onClick={handleRetryInstall}>
                                重试安装
                              </Button>
                            </div>
                          )}
                          {!depsStatus.installing && !depsStatus.last_error
                           && depsStatus.lark_oapi_installed && depsStatus.lark_cli_installed
                           && depsStatus.lark_cli_app_matches && (
                            <div className="text-xs text-green-500">
                              ✓ 全部就绪，重启 ethan serve 后将自动建立飞书长连接
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </CardContent>
                )}
              </Card>
            );
          })}
          {/* 未来渠道占位 */}
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
      </ScrollArea>
    </div>
  );
}

function DepsRow({ label, ok, installing }: { label: string; ok: boolean; installing: boolean }) {
  return (
    <div className="flex items-center gap-2">
      {installing ? (
        <Loader2 className="h-3 w-3 animate-spin text-yellow-600" />
      ) : ok ? (
        <CheckCircle2 className="h-3 w-3 text-green-500" />
      ) : (
        <XCircle className="h-3 w-3 text-red-500" />
      )}
      <span className={ok ? "text-foreground" : "text-muted-foreground"}>{label}</span>
    </div>
  );
}
