"use client";

import { useEffect, useState } from "react";
import { ChannelInfo, fetchChannels, patchChannel } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChevronDown, ChevronRight } from "lucide-react";

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

  useEffect(() => {
    fetchChannels().then(data => {
      setChannels(data);
      const initial: Record<string, Record<string, string>> = {};
      for (const ch of data) initial[ch.id] = { ...ch.config };
      setForms(initial);
    }).catch(() => {});
  }, []);

  const handleSave = async (channelId: string) => {
    setSaving(channelId);
    try {
      await patchChannel(channelId, forms[channelId] || {});
      const updated = await fetchChannels();
      setChannels(updated);
      setMessages(prev => ({ ...prev, [channelId]: { type: "success", text: "已保存" } }));
      setTimeout(() => setMessages(prev => { const n = { ...prev }; delete n[channelId]; return n; }), 3000);
    } catch {
      setMessages(prev => ({ ...prev, [channelId]: { type: "error", text: "保存失败" } }));
    } finally {
      setSaving(null);
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
