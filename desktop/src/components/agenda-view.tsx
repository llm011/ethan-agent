import { useEffect, useState, useCallback, useMemo } from "react";
import {
  AgendaEvent, AgendaRepeat, fetchAgenda, createAgendaEvent, updateAgendaEvent,
  completeAgendaEvent, deleteAgendaEvent, setAgendaEnabled,
} from "@/lib/api";
import { Badge } from "@ethan/shared/ui/badge";
import { Button } from "@ethan/shared/ui/button";
import { ScrollArea } from "@ethan/shared/ui/scroll-area";
import { Loader2, RefreshCw, Trash2, Pencil, Check, Plus, CalendarClock, BellRing } from "lucide-react";
import { ConfirmDialog } from "@ethan/shared/components/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ethan/shared/ui/dialog";
import { Input } from "@ethan/shared/ui/input";
import { Textarea } from "@ethan/shared/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ethan/shared/ui/select";
import { addHandler, removeHandler } from "@/lib/desktop-ws";

// ── Helpers ─────────────────────────────────────────────────────

const WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"]; // ISO 1..7

function repeatLabel(ev: AgendaEvent): string {
  if (ev.repeat === "daily") return "每天";
  if (ev.repeat === "weekly") {
    const days = (ev.weekdays || []).slice().sort((a, b) => a - b).map(d => `周${WEEKDAY_LABELS[d - 1] || d}`).join("、");
    return days || "每周";
  }
  return "";
}

/** 解析 'YYYY-MM-DD HH:MM' → Date（本地时区）；失败返回 null */
function parseWhen(when: string): Date | null {
  const m = when.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]));
  return isNaN(d.getTime()) ? null : d;
}

function dateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

interface DateGroup {
  key: string;
  day: number;
  month: number;
  year: number;
  isToday: boolean;
  isPast: boolean;
  events: AgendaEvent[];
}

/** 把事件按「下一次触发时间」分组成日期组；无下次时间的（fired/missed/done）按 when 日期归档 */
function groupEventsByDate(events: AgendaEvent[]): DateGroup[] {
  const todayKey = dateKey(new Date());
  const map = new Map<string, DateGroup>();

  for (const ev of events) {
    const d = (ev.status === "pending" && ev.next_run_time)
      ? new Date(ev.next_run_time)
      : parseWhen(ev.when);
    if (!d || isNaN(d.getTime())) continue;
    const key = dateKey(d);
    if (!map.has(key)) {
      map.set(key, {
        key, day: d.getDate(), month: d.getMonth() + 1, year: d.getFullYear(),
        isToday: key === todayKey,
        isPast: key < todayKey,
        events: [],
      });
    }
    map.get(key)!.events.push({ ...ev, _sort: d.getTime() } as any);
  }

  const groups = Array.from(map.values()).sort((a, b) => a.key.localeCompare(b.key));
  for (const g of groups) {
    g.events.sort((a, b) => ((a as any)._sort ?? 0) - ((b as any)._sort ?? 0));
  }
  return groups;
}

// ── 事件编辑弹窗 ─────────────────────────────────────────────────

interface EventDraft {
  title: string;
  whenLocal: string;  // datetime-local 格式 'YYYY-MM-DDTHH:mm'
  repeat: AgendaRepeat;
  weekdays: number[];
  note: string;
}

function draftFromEvent(ev: AgendaEvent | null): EventDraft {
  if (!ev) {
    // 默认：一小时后的整点
    const d = new Date(Date.now() + 60 * 60 * 1000);
    d.setMinutes(0, 0, 0);
    return {
      title: "",
      whenLocal: `${dateKey(d)}T${String(d.getHours()).padStart(2, "0")}:00`,
      repeat: "none",
      weekdays: [],
      note: "",
    };
  }
  const d = parseWhen(ev.when);
  return {
    title: ev.title,
    whenLocal: d
      ? `${dateKey(d)}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
      : ev.when.replace(" ", "T").slice(0, 16),
    repeat: ev.repeat,
    weekdays: ev.weekdays || [],
    note: ev.note || "",
  };
}

function EventDialog({ open, editing, onConfirm, onCancel }: {
  open: boolean;
  editing: AgendaEvent | null;
  onConfirm: (draft: EventDraft) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<EventDraft>(draftFromEvent(null));
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setDraft(draftFromEvent(editing));
      setError("");
    }
  }, [open, editing]);

  const valid = draft.title.trim() && draft.whenLocal && (draft.repeat !== "weekly" || draft.weekdays.length > 0);

  const submit = () => {
    if (!valid) return;
    onConfirm(draft);
  };

  return (
    <Dialog open={open} onOpenChange={(o: boolean) => !o && onCancel()}>
      <DialogContent showCloseButton={false} className="max-w-md">
        <DialogHeader>
          <DialogTitle>{editing ? "编辑日程" : "添加日程"}</DialogTitle>
          <DialogDescription className="mt-1">
            时间到了会发送桌面通知{editing ? "；修改后立即生效" : ""}。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-1">
          <Input
            value={draft.title}
            onChange={(e) => setDraft(d => ({ ...d, title: e.target.value }))}
            placeholder="要做什么？（如：下午 3 点开周会）"
            autoFocus
          />
          <Input
            type="datetime-local"
            value={draft.whenLocal}
            onChange={(e) => setDraft(d => ({ ...d, whenLocal: e.target.value }))}
          />
          <div className="flex items-center gap-2">
            <Select
              value={draft.repeat}
              onValueChange={(v) => v && setDraft(d => ({ ...d, repeat: v as AgendaRepeat }))}
            >
              <SelectTrigger className="w-[120px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">单次</SelectItem>
                <SelectItem value="daily">每天</SelectItem>
                <SelectItem value="weekly">每周</SelectItem>
              </SelectContent>
            </Select>
            {draft.repeat === "weekly" && (
              <div className="flex gap-1">
                {WEEKDAY_LABELS.map((label, i) => {
                  const iso = i + 1;
                  const active = draft.weekdays.includes(iso);
                  return (
                    <button
                      key={iso}
                      type="button"
                      className={`h-7 w-7 rounded-md text-xs transition-colors ${
                        active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground"
                      }`}
                      onClick={() => setDraft(d => ({
                        ...d,
                        weekdays: active
                          ? d.weekdays.filter(x => x !== iso)
                          : [...d.weekdays, iso],
                      }))}
                    >{label}</button>
                  );
                })}
              </div>
            )}
          </div>
          <Textarea
            value={draft.note}
            onChange={(e) => setDraft(d => ({ ...d, note: e.target.value }))}
            placeholder="备注（可选）"
            className="min-h-[60px]"
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>取消</Button>
          <Button onClick={submit} disabled={!valid}>
            {editing ? "保存" : "添加"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── 主视图 ───────────────────────────────────────────────────────

const STATUS_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  pending: { label: "待提醒", variant: "default" },
  fired: { label: "已提醒", variant: "secondary" },
  missed: { label: "已错过", variant: "destructive" },
  done: { label: "已完成", variant: "outline" },
};

export function AgendaView() {
  const [events, setEvents] = useState<AgendaEvent[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<"today" | "all">("today");
  const [confirmState, setConfirmState] = useState<{ open: boolean; id: string }>({ open: false, id: "" });
  const [dialogState, setDialogState] = useState<{ open: boolean; editing: AgendaEvent | null }>({ open: false, editing: null });
  const [togglingEnabled, setTogglingEnabled] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchAgenda();
      setEvents(data.events);
      setEnabled(data.enabled);
    } catch (e) {
      console.error("Failed to load agenda", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // 监听后端 WS 推送（日程到点/错过时自动刷新列表）
  useEffect(() => {
    const handler = (method: string) => {
      if (method === "agenda_changed") loadData();
    };
    addHandler(handler);
    return () => removeHandler(handler);
  }, [loadData]);

  // today 模式：过去未完成的（missed）+ 今天 + 未来；all 模式：全部
  const visibleEvents = useMemo(() => {
    if (viewMode === "all") return events;
    const todayKey = dateKey(new Date());
    return events.filter(ev => {
      if (ev.status === "pending") return true;
      const d = parseWhen(ev.when);
      return !d || dateKey(d) >= todayKey; // 保留今天的 fired/done，隐藏更早的历史
    });
  }, [events, viewMode]);

  const dateGroups = useMemo(() => groupEventsByDate(visibleEvents), [visibleEvents]);

  const toggleEnabled = async (next: boolean) => {
    setEnabled(next); // 乐观更新
    setTogglingEnabled(true);
    try {
      await setAgendaEnabled(next);
    } catch (e) {
      console.error("Failed to toggle agenda enabled", e);
      setEnabled(!next);
    } finally {
      setTogglingEnabled(false);
    }
  };

  const submitEvent = async (draft: EventDraft) => {
    const editing = dialogState.editing;
    setDialogState({ open: false, editing: null });
    const when = draft.whenLocal.replace("T", " "); // 'YYYY-MM-DD HH:MM'
    try {
      if (editing) {
        await updateAgendaEvent(editing.id, {
          title: draft.title.trim(), when,
          repeat: draft.repeat, weekdays: draft.weekdays, note: draft.note,
        });
      } else {
        await createAgendaEvent({
          title: draft.title.trim(), when,
          repeat: draft.repeat, weekdays: draft.weekdays, note: draft.note,
        });
      }
      await loadData();
    } catch (e) {
      console.error("Failed to save agenda event", e);
      alert(e instanceof Error ? e.message : "保存日程失败");
      await loadData();
    }
  };

  const doComplete = async (ev: AgendaEvent) => {
    setEvents(prev => prev.map(e => e.id === ev.id ? { ...e, status: "done" } : e));
    try {
      await completeAgendaEvent(ev.id);
      await loadData();
    } catch (e) {
      console.error("Failed to complete agenda event", e);
      await loadData();
    }
  };

  const doRemove = async () => {
    const id = confirmState.id;
    setConfirmState({ open: false, id: "" });
    setEvents(prev => prev.filter(e => e.id !== id));
    try {
      await deleteAgendaEvent(id);
    } catch (e) {
      console.error("Failed to delete agenda event", e);
      await loadData();
    }
  };

  return (
    <div className="flex flex-col h-full bg-background text-foreground">
      <ConfirmDialog
        open={confirmState.open}
        title="删除日程"
        description="确定要删除这个日程吗？此操作无法撤销。"
        confirmLabel="删除"
        onConfirm={doRemove}
        onCancel={() => setConfirmState({ open: false, id: "" })}
      />
      <EventDialog
        open={dialogState.open}
        editing={dialogState.editing}
        onConfirm={submitEvent}
        onCancel={() => setDialogState({ open: false, editing: null })}
      />

      <header className="h-12 border-b border-border flex items-center px-4 justify-between shrink-0">
        <h1 className="font-semibold text-lg">日程 (Agenda)</h1>
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-md border border-border overflow-hidden">
            <button
              onClick={() => setViewMode("today")}
              className={`px-2.5 py-1 text-xs transition-colors ${
                viewMode === "today" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
            >今天</button>
            <button
              onClick={() => setViewMode("all")}
              className={`px-2.5 py-1 text-xs transition-colors ${
                viewMode === "all" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
            >全部</button>
          </div>
          <Button variant="ghost" size="icon" onClick={loadData} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </header>

      {/* Agent 日程工具开关（特殊插件） */}
      <div className="border-b border-border px-4 py-2.5 flex items-center justify-between gap-4 shrink-0">
        <div className="flex items-start gap-2 min-w-0">
          <BellRing className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <div className="text-sm font-medium">Agent 日程工具</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              开启后，Agent 获得 agenda_add / agenda_update / agenda_complete / agenda_list / agenda_delete 工具，可以帮你管理日程。
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {togglingEnabled && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
          <button
            onClick={() => void toggleEnabled(!enabled)}
            role="switch"
            aria-checked={enabled}
            className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${enabled ? "bg-primary" : "bg-muted"}`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-background transition-transform ${enabled ? "translate-x-4" : "translate-x-0.5"}`}
            />
          </button>
        </div>
      </div>

      {/* 添加按钮 */}
      <div className="px-4 pt-3 shrink-0">
        <Button size="sm" onClick={() => setDialogState({ open: true, editing: null })}>
          <Plus className="h-3.5 w-3.5 mr-1.5" /> 添加日程
        </Button>
      </div>

      {/* 时间轴 */}
      <ScrollArea className="flex-1 p-4 pt-3">
        {loading && events.length === 0 ? (
          <div className="flex items-center justify-center h-full pt-10">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : dateGroups.length === 0 ? (
          <div className="text-center text-muted-foreground pt-10">
            {viewMode === "today" ? "暂无待办日程，点击上方「添加日程」创建" : "暂无日程"}
          </div>
        ) : (
          <div className="relative pl-2">
            <div className="absolute left-[91px] top-0 bottom-0 w-px bg-border" />
            {dateGroups.map((group, gi) => {
              const prevGroup = gi > 0 ? dateGroups[gi - 1] : null;
              const showYearMonth = gi === 0 || !prevGroup || prevGroup.year !== group.year || prevGroup.month !== group.month;
              return (
                <div key={group.key} className="relative">
                  {showYearMonth && (
                    <div className="flex items-baseline gap-1 shrink-0 min-w-[80px] mb-2 mt-4 first:mt-0">
                      <span className="text-lg font-bold text-foreground">{group.month}月</span>
                      <span className="text-xs text-muted-foreground">{group.year}</span>
                    </div>
                  )}
                  <div className="flex gap-0">
                    <div className="w-[80px] shrink-0 pt-1 flex items-baseline gap-1.5">
                      <span className="text-xs font-semibold text-muted-foreground">{group.day}日</span>
                      {group.isToday && (
                        <span className="text-[10px] text-primary font-medium">今天</span>
                      )}
                    </div>
                    <div className="relative flex-1 pb-4">
                      {group.events.map((ev) => {
                        const d = (ev.status === "pending" && ev.next_run_time)
                          ? new Date(ev.next_run_time)
                          : parseWhen(ev.when);
                        const timeStr = d && !isNaN(d.getTime())
                          ? d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })
                          : "--:--";
                        const badge = STATUS_BADGE[ev.status] || STATUS_BADGE.pending;
                        const rep = repeatLabel(ev);
                        return (
                          <div key={ev.id} className="relative flex items-start gap-3 group mb-2 last:mb-0">
                            <div className={`relative z-10 mt-2.5 w-[7px] h-[7px] rounded-full shrink-0 ring-2 ring-background ${
                              ev.status === "pending" ? "bg-primary" : ev.status === "missed" ? "bg-destructive" : "bg-muted-foreground/40"
                            }`} />
                            <span className="text-[11px] font-mono text-muted-foreground mt-2 w-[38px] shrink-0">{timeStr}</span>
                            <div className={`flex-1 min-w-0 max-w-[520px] border border-border/50 rounded-lg px-3 py-2 transition-colors hover:border-border hover:bg-muted/20 ${
                              ev.status === "done" ? "opacity-60" : ""
                            }`}>
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-2 min-w-0">
                                  <span className={`text-sm font-medium truncate ${ev.status === "done" ? "line-through" : ""}`}>{ev.title}</span>
                                  <Badge variant={badge.variant} className="text-[9px] px-1.5 py-0 h-4 shrink-0">{badge.label}</Badge>
                                  {rep && (
                                    <Badge variant="outline" className="text-[9px] px-1.5 py-0 h-4 shrink-0">{rep}</Badge>
                                  )}
                                </div>
                                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                                  {ev.status !== "done" && (
                                    <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => void doComplete(ev)} title="标记完成">
                                      <Check className="h-3 w-3" />
                                    </Button>
                                  )}
                                  <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setDialogState({ open: true, editing: ev })} title="编辑">
                                    <Pencil className="h-3 w-3" />
                                  </Button>
                                  <Button variant="ghost" size="icon" className="h-6 w-6 text-destructive/70 hover:text-destructive" onClick={() => setConfirmState({ open: true, id: ev.id })} title="删除">
                                    <Trash2 className="h-3 w-3" />
                                  </Button>
                                </div>
                              </div>
                              {ev.note && (
                                <p className="mt-1 text-[11px] text-muted-foreground whitespace-pre-wrap break-words line-clamp-2">{ev.note}</p>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
