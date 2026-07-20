import { useState, useEffect } from "react";
import { Button } from "@ethan/shared/ui/button";
import { Input } from "@ethan/shared/ui/input";
import {
  fetchFastRules, fetchFastRuleOptions, updateFastRules,
  FastRules, FastRule, FastRuleOptions,
} from "@/lib/api";

export function FastRulesTab() {
  const [data, setData] = useState<FastRules | null>(null);
  const [options, setOptions] = useState<FastRuleOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [d, o] = await Promise.all([fetchFastRules(), fetchFastRuleOptions()]);
        setData(d);
        setOptions(o);
      } catch (e) {
        console.error("Failed to load fast rules", e);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const save = async () => {
    if (!data) return;
    setSaving(true);
    try {
      await updateFastRules(data);
      setSavedAt(Date.now());
      setTimeout(() => setSavedAt(null), 2000);
    } finally {
      setSaving(false);
    }
  };

  const updateRule = (idx: number, patch: Partial<FastRule>) => {
    if (!data) return;
    const rules = data.fast_rules.map((r, i) => (i === idx ? { ...r, ...patch } : r));
    setData({ ...data, fast_rules: rules });
  };

  const addRule = () => {
    if (!data) return;
    setData({ ...data, fast_rules: [...data.fast_rules, { name: "新规则", keywords: [], tools: [], skills: [] }] });
  };

  const removeRule = (idx: number) => {
    if (!data) return;
    setData({ ...data, fast_rules: data.fast_rules.filter((_, i) => i !== idx) });
  };

  const toggle = (list: string[], name: string): string[] =>
    list.includes(name) ? list.filter((x) => x !== name) : [...list, name];

  if (loading || !data || !options) {
    return <div className="text-sm text-muted-foreground p-4">加载中…</div>;
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h3 className="text-lg font-medium">快捷路由（Fast 规则）</h3>
        <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
          命中规则关键字的消息走 Fast Path：极简 prompt + lite 模型，最快最省。
          Fast 档固定挂载下方「基础系统工具」，命中某条规则时再额外挂载该规则勾选的工具/技能，
          其余长尾能力模型会自行用 <code className="text-xs font-mono">find_tools</code> 激活兜底。
          未命中任何规则的消息按长度走 medium / full。
        </p>
      </div>

      <div className="rounded-lg border border-border/60 p-4 bg-muted/10">
        <div className="text-sm font-medium mb-1">基础系统工具（Fast 档始终挂载）</div>
        <p className="text-xs text-muted-foreground mb-3">所有 Fast 请求都带上这些，无需逐条规则重复配置。</p>
        <div className="flex flex-wrap gap-1.5">
          {options.tools.map((t) => {
            const on = data.fast_base_tools.includes(t.name);
            return (
              <button
                key={t.name}
                title={t.description}
                onClick={() => setData({ ...data, fast_base_tools: toggle(data.fast_base_tools, t.name) })}
                className={`px-2 py-1 rounded-md text-xs font-mono border transition-colors ${
                  on ? "bg-primary text-primary-foreground border-primary" : "bg-background border-border text-muted-foreground hover:border-primary/50"
                }`}
              >
                {t.name}
              </button>
            );
          })}
        </div>
      </div>

      {data.fast_rules.map((rule, idx) => (
        <div key={idx} className="rounded-lg border border-border/60 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <Input
              value={rule.name}
              onChange={(e) => updateRule(idx, { name: e.target.value })}
              placeholder="规则名（如 智能家居控制）"
              className="h-8 text-sm font-medium max-w-xs"
            />
            <div className="flex-1" />
            <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => removeRule(idx)}>
              删除规则
            </Button>
          </div>

          <div className="grid gap-1.5">
            <label className="text-xs text-muted-foreground">触发关键字（命中任一即走 Fast，支持通配 *，每行一个）</label>
            <textarea
              className="font-mono text-sm bg-background border border-border rounded-md px-3 py-2 outline-none focus:ring-2 focus:ring-ring resize-none"
              rows={4}
              value={rule.keywords.join("\n")}
              onChange={(e) => updateRule(idx, { keywords: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })}
              placeholder={"关*灯\n开*灯"}
            />
          </div>

          <div className="grid gap-1.5">
            <label className="text-xs text-muted-foreground">额外挂载工具（在基础工具之上）</label>
            <div className="flex flex-wrap gap-1.5">
              {options.tools.map((t) => {
                const on = rule.tools.includes(t.name);
                return (
                  <button
                    key={t.name}
                    title={t.description}
                    onClick={() => updateRule(idx, { tools: toggle(rule.tools, t.name) })}
                    className={`px-2 py-1 rounded-md text-xs font-mono border transition-colors ${
                      on ? "bg-sky-600 text-white border-sky-600" : "bg-background border-border text-muted-foreground hover:border-sky-500/50"
                    }`}
                  >
                    {t.name}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid gap-1.5">
            <label className="text-xs text-muted-foreground">注入技能（命中即强制注入 prompt，不靠技能自身触发词）</label>
            <div className="flex flex-wrap gap-1.5">
              {options.skills.map((s) => {
                const on = rule.skills.includes(s.name);
                return (
                  <button
                    key={s.name}
                    title={s.description}
                    onClick={() => updateRule(idx, { skills: toggle(rule.skills, s.name) })}
                    className={`px-2 py-1 rounded-md text-xs border transition-colors ${
                      on ? "bg-violet-600 text-white border-violet-600" : "bg-background border-border text-muted-foreground hover:border-violet-500/50"
                    }`}
                  >
                    {s.name}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      ))}

      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" onClick={addRule}>+ 新增规则</Button>
        <div className="flex-1" />
        {savedAt && <span className="text-xs text-emerald-500">已保存</span>}
        <Button size="sm" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存"}</Button>
      </div>
    </div>
  );
}
