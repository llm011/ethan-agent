"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import {
  AgendaEvent, AgendaRepeat, fetchAgenda, createAgendaEvent, updateAgendaEvent,
  completeAgendaEvent, deleteAgendaEvent, setAgendaEnabled,
} from "@/lib/api-misc";
import { Badge } from "@ethan/shared/ui/badge";
import { Button } from "@ethan/shared/ui/button";
import { Loader2, RefreshCw, Trash2, Pencil, Check, Plus, BellRing, ChevronLeft, ChevronRight } from "lucide-react";
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

// ── Helpers ─────────────────────────────────────────────────────

const WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"];
const WEEKDAY_SHORT = ["一", "二", "三", "四", "五", "六", "日"];

function repeatLabel(ev: AgendaEvent): string {
  if (ev.repeat === "daily") return "每天";
  if (ev.repeat === "weekly") {
    const days = (ev.weekdays || []).slice().sort((a, b) => a - b).map(d => `周${WEEKDAY_LABELS[d - 1] || d}`).join("、");
    return days || "每周";
  }
  return "";
}

function parseWhen(when: string): Date | null {
  const m = when.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]));
  return isNaN(d.getTime()) ? null : d;
}

function dateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function getISOWeekday(d: Date): number {
  return d.getDay() === 0 ? 7 : d.getDay();
}

interface DateGroup {
  key: string;
  day: number;
  month: number;
  year: number;
  isToday: boolean;
  isPast: boolean;
  events: (AgendaEvent & { _sort?: number })[];
}

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
    map.get(key)!.events.push({ ...ev, _sort: d.getTime() });
  }

  const groups = Array.from(map.values()).sort((a, b) => a.key.localeCompare(b.key));
  for (const g of groups) {
    g.events.sort((a, b) => (a._sort ?? 0) - (b._sort ?? 0));
  }
  return groups;
}

// ── 当前时间指示器 ─────────────────────────────────────────────────

function useNow(intervalMs = 1000): Date {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

function NowIndicator({ now }: { now: Date }) {
  const timeStr = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  return (
    <div className="relative flex items-center gap-0 my-1 -ml-[3px]">
      <div className="w-[7px] h-[7px] rounded-full bg-red-500 shrink-0 z-10" />
      <div className="flex-1 h-px bg-red-500/70" />
      <span className="text-[9px] font-mono text-red-500 ml-1.5 shrink-0 tabular-nums">{timeStr}</span>
    </div>
  );
}

// ── 月历导航组件 ─────────────────────────────────────────────────

function MonthCalendar({ currentDate, eventDates, onSelectDate }: {
  currentDate: Date;
  eventDates: Set<string>;
  onSelectDate: (key: string) => void;
}) {
  const [displayMonth, setDisplayMonth] = useState(() => startOfMonth(currentDate));
  const todayKey = dateKey(new Date());

  const daysInMonth = new Date(displayMonth.getFullYear(), displayMonth.getMonth() + 1, 0).getDate();
  const firstWeekday = getISOWeekday(displayMonth); // 1=Mon

  const cells: (Date | null)[] = [];
  for (let i = 1; i < firstWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push(new Date(displayMonth.getFullYear(), displayMonth.getMonth(), d));
  }

  const prevMonth = () => setDisplayMonth(new Date(displayMonth.getFullYear(), displayMonth.getMonth() - 1, 1));
  const nextMonth = () => setDisplayMonth(new Date(displayMonth.getFullYear(), displayMonth.getMonth() + 1, 1));
  const goToday = () => {
    setDisplayMonth(startOfMonth(new Date()));
    onSelectDate(todayKey);
  };

  const selectedKey = dateKey(currentDate);

  return (
    <div className="px-3 py-3 shrink-0">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1">
          <button onClick={prevMonth} className="p-0.5 rounded hover:bg-muted transition-colors">
            <ChevronLeft className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
          <span className="text-xs font-medium min-w-[70px] text-center">
            {displayMonth.getFullYear()}年{displayMonth.getMonth() + 1}月
          </span>
          <button onClick={nextMonth} className="p-0.5 rounded hover:bg-muted transition-colors">
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        </div>
        <button
          onClick={goToday}
          className="text-[10px] text-primary hover:text-primary/80 font-medium px-1.5 py-0.5 rounded hover:bg-primary/10 transition-colors"
        >
          今天
        </button>
      </div>
      <div className="grid grid-cols-7 gap-0">
        {WEEKDAY_SHORT.map(w => (
          <div key={w} className="text-center text-[9px] text-muted-foreground py-0.5">{w}</div>
        ))}
        {cells.map((date, i) => {
          if (!date) return <div key={`empty-${i}`} />;
          const key = dateKey(date);
          const isToday = key === todayKey;
          const isSelected = key === selectedKey;
          const hasEvent = eventDates.has(key);
          return (
            <button
              key={key}
              onClick={() => onSelectDate(key)}
              className={`relative flex flex-col items-center justify-center h-7 rounded text-[11px] transition-colors ${
                isSelected
                  ? "bg-primary text-primary-foreground"
                  : isToday
                    ? "bg-primary/10 text-primary font-semibold"
                    : "hover:bg-muted text-foreground"
              }`}
            >
              {date.getDate()}
              {hasEvent && (
                <span className={`absolute bottom-0.5 w-1 h-1 rounded-full ${
                  isSelected ? "bg-primary-foreground" : "bg-primary"
                }`} />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── 事件编辑弹窗 ─────────────────────────────────────────────────

interface EventDraft {
  title: string;
  whenLocal: string;
  repeat: AgendaRepeat;
  weekdays: number[];
  note: string;
}

function draftFromEvent(ev: AgendaEvent | null): EventDraft {
  if (!ev) {
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
      <DialogContent className="max-w-md">
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
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());
  const [confirmState, setConfirmState] = useState<{ open: boolean; id: string }>({ open: false, id: "" });
  const [dialogState, setDialogState] = useState<{ open: boolean; editing: AgendaEvent | null }>({ open: false, editing: null });
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  const [scrolledToToday, setScrolledToToday] = useState(false);
  const timelineRef = useRef<HTMLDivElement>(null);
  const groupRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const now = useNow();

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

  useEffect(() => {
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  const dateGroups = useMemo(() => groupEventsByDate(events), [events]);

  const eventDates = useMemo(() => {
    const set = new Set<string>();
    for (const ev of events) {
      const d = (ev.status === "pending" && ev.next_run_time)
        ? new Date(ev.next_run_time)
        : parseWhen(ev.when);
      if (d && !isNaN(d.getTime())) set.add(dateKey(d));
    }
    return set;
  }, [events]);

  // 首次加载完成后自动滚到今天
  useEffect(() => {
    if (!loading && dateGroups.length > 0 && !scrolledToToday) {
      setScrolledToToday(true);
      const todayKey = dateKey(new Date());
      scrollToDate(todayKey);
    }
  }, [loading, dateGroups, scrolledToToday]);

  const scrollToDate = (key: string) => {
    const el = groupRefs.current.get(key);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      // 如果目标日期没有事件，滚动到最近的有事件的日期
      const sorted = dateGroups.map(g => g.key).sort();
      const closest = sorted.find(k => k >= key) || sorted[sorted.length - 1];
      if (closest) {
        const closestEl = groupRefs.current.get(closest);
        closestEl?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  };

  const handleSelectDate = (key: string) => {
    const parts = key.split("-").map(Number);
    setSelectedDate(new Date(parts[0], parts[1] - 1, parts[2]));
    scrollToDate(key);
  };

  const toggleEnabled = async (next: boolean) => {
    setEnabled(next);
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
    const when = draft.whenLocal.replace("T", " ");
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
          <Button size="sm" variant="outline" onClick={() => setDialogState({ open: true, editing: null })}>
            <Plus className="h-3.5 w-3.5 mr-1.5" /> 添加
          </Button>
          <Button variant="ghost" size="icon" onClick={loadData} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </header>

      {/* 左右布局：左侧时间轴（主体） + 右侧月历 */}
      <div className="flex flex-1 min-h-0">
        {/* 左侧：时间轴 */}
        <div ref={timelineRef} className="flex-1 overflow-y-auto p-4 pt-3 min-w-0">
          {loading && events.length === 0 ? (
            <div className="flex items-center justify-center h-full pt-10">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : dateGroups.length === 0 ? (
            <div className="text-center text-muted-foreground pt-10">
              暂无日程，点击右上角「添加」创建
            </div>
          ) : (
            <div className="relative pl-2">
              <div className="absolute left-[91px] top-0 bottom-0 w-px bg-border" />
              {dateGroups.map((group, gi) => {
                const prevGroup = gi > 0 ? dateGroups[gi - 1] : null;
                const showYearMonth = gi === 0 || !prevGroup || prevGroup.year !== group.year || prevGroup.month !== group.month;
                return (
                  <div
                    key={group.key}
                    className="relative"
                    ref={(el) => { if (el) groupRefs.current.set(group.key, el); }}
                  >
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
                        {(() => {
                          const nowTs = now.getTime();
                          let nowInserted = false;
                          const items: React.ReactNode[] = [];
                          for (const ev of group.events) {
                            const d = (ev.status === "pending" && ev.next_run_time)
                              ? new Date(ev.next_run_time)
                              : parseWhen(ev.when);
                            const evTs = d && !isNaN(d.getTime()) ? d.getTime() : 0;
                            if (group.isToday && !nowInserted && evTs > nowTs) {
                              items.push(<NowIndicator key="__now__" now={now} />);
                              nowInserted = true;
                            }
                            const timeStr = d && !isNaN(d.getTime())
                              ? d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })
                              : "--:--";
                            const badge = STATUS_BADGE[ev.status] || STATUS_BADGE.pending;
                            const rep = repeatLabel(ev);
                            items.push(
                              <div key={ev.id} className="relative flex items-start gap-3 group mb-2 last:mb-0">
                                <div className={`relative z-10 mt-2.5 w-[7px] h-[7px] rounded-full shrink-0 ring-2 ring-background ${
                                  ev.status === "pending" ? "bg-primary" : ev.status === "missed" ? "bg-destructive" : "bg-muted-foreground/40"
                                }`} />
                                <span className="text-[11px] font-mono text-muted-foreground mt-2 w-[38px] shrink-0">{timeStr}</span>
                                <div className={`flex-1 min-w-0 border border-border/50 rounded-lg px-3 py-2 transition-colors hover:border-border hover:bg-muted/20 ${
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
                          }
                          if (group.isToday && !nowInserted) {
                            items.push(<NowIndicator key="__now__" now={now} />);
                          }
                          return items;
                        })()}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 右侧：月历 + Agent 开关 */}
        <div className="w-[220px] shrink-0 border-l border-border flex flex-col">
          <MonthCalendar
            currentDate={selectedDate}
            eventDates={eventDates}
            onSelectDate={handleSelectDate}
          />
          <div className="px-3 py-2 flex items-center justify-between gap-2 mt-auto border-t border-border">
            <div className="flex items-center gap-1.5 min-w-0">
              <BellRing className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="text-[10px] text-muted-foreground truncate">Agent 工具</span>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              {togglingEnabled && <Loader2 className="h-2.5 w-2.5 animate-spin text-muted-foreground" />}
              <button
                onClick={() => void toggleEnabled(!enabled)}
                role="switch"
                aria-checked={enabled}
                className={`relative inline-flex h-3.5 w-6 shrink-0 items-center rounded-full transition-colors ${enabled ? "bg-primary" : "bg-muted"}`}
              >
                <span
                  className={`inline-block h-2.5 w-2.5 transform rounded-full bg-background transition-transform ${enabled ? "translate-x-3" : "translate-x-0.5"}`}
                />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
