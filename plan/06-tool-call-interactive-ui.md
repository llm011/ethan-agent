# Web 端工具调用时间轴交互

## 背景与目标

当前 Web 端工具调用体验粗糙：执行时只有一行 `⚡ shell(...)` 闪烁文字，完成后消失。
用户看不到推理过程，不知道 Agent 做了什么。

**目标：实现类 Claude Desktop 的时间轴交互。**
- 每个工具调用有 icon、名称、参数摘要、执行状态（运行中/完成/出错）和耗时
- 所有工具完成后时间轴**自动折叠**，只留标题行"N actions"
- 用户可点击标题行手动展开/折叠
- 正式回复出现在时间轴下方

---

## 现状分析

### 后端 SSE（`ethan/interface/api.py` `_stream_response()`）

当前三种事件：
```
data: {"tool": "shell", "args": "ls -la", "state": "start"}
data: {"tool": "shell", "args": "", "state": "done", "result_preview": "..."}
data: {"content": "回复文字..."}
data: {"done": true, "usage": {...}}
```

缺失：`duration_ms`（工具执行耗时）。

### 前端现状（`web/components/chat-view.tsx`）

```typescript
// Message interface
interface Message {
  toolActivity?: string;   // 只有一条文字，完成后消失
  ...
}

// 渲染（约 416 行）
{msg.toolActivity && (
  <div className="text-xs text-muted-foreground mb-2">
    <span className="animate-pulse">⚡</span>
    <span>{msg.toolActivity}</span>
  </div>
)}
```

工具调用完成后完全消失，没有持久化记录。

---

## 实现方案

### 一、后端改动（`ethan/interface/api.py`）

在 `_stream_response()` 里记录工具开始时间，完成时附带 `duration_ms`：

```python
import time as _time

async def _stream_response(agent, messages, store, session_id):
    from ethan.providers.base import ToolEvent
    import asyncio

    tool_start_times: dict[str, float] = {}
    full = ""

    try:
        async for item in agent.stream_chat(messages):
            if isinstance(item, ToolEvent):
                if item.state == "start":
                    tool_start_times[item.tool_name] = _time.time()
                    evt = {
                        "tool": item.tool_name,
                        "args": item.args_summary,
                        "state": "start",
                    }
                else:
                    duration_ms = int(
                        (_time.time() - tool_start_times.pop(item.tool_name, _time.time())) * 1000
                    )
                    evt = {
                        "tool": item.tool_name,
                        "args": item.args_summary,
                        "state": item.state,
                        "duration_ms": duration_ms,
                        "result_preview": item.result_preview or "",
                    }
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            else:
                full += item
                yield f"data: {json.dumps({'content': item}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

    # done 事件以及后续持久化逻辑不变
    ...
```

**改动量：约 12 行。**

---

### 二、前端改动

#### 1. 扩展 Message 类型（`web/components/chat-view.tsx`）

```typescript
// 新增 ToolStep interface（放在 Message interface 上方）
interface ToolStep {
  tool: string;             // 工具名，如 "shell"、"web_search"
  args: string;             // 参数摘要
  state: "running" | "done" | "error";
  duration_ms?: number;
  result_preview?: string;
}

// 修改 Message interface
interface Message {
  role: "user" | "assistant";
  content: string;
  files?: string[];
  toolSteps?: ToolStep[];      // 替换原来的 toolActivity?: string
  toolsExpanded?: boolean;     // 时间轴是否展开
  created_at?: number;
  usage?: { input: number; output: number; cache: number };
  ttft?: number;
}
```

#### 2. 修改 `handleSend` 里的 SSE 处理逻辑

替换原来的 `currentActivity` 逻辑（约第 232 行开始）：

```typescript
// 删除这行：
// let currentActivity = "";

// 新增：
const currentToolSteps: ToolStep[] = [];

// 在 for await 循环里：

// 替换 chunk.tool && state === "start" 的处理：
if (chunk.tool && chunk.state === "start") {
  currentToolSteps.push({
    tool: chunk.tool,
    args: chunk.args || "",
    state: "running",
  });
  setMessages([...newMessages, {
    role: "assistant",
    content: assistantContent,
    toolSteps: [...currentToolSteps],
    toolsExpanded: true,
    created_at: Date.now() / 1000,
  }]);
}

// 替换 chunk.tool && state !== "start" 的处理：
if (chunk.tool && (chunk.state === "done" || chunk.state === "error")) {
  // 找到最后一个同名且 running 的 step，更新状态
  for (let i = currentToolSteps.length - 1; i >= 0; i--) {
    if (currentToolSteps[i].tool === chunk.tool && currentToolSteps[i].state === "running") {
      currentToolSteps[i] = {
        ...currentToolSteps[i],
        state: chunk.state as "done" | "error",
        duration_ms: chunk.duration_ms,
        result_preview: chunk.result_preview,
      };
      break;
    }
  }
  setMessages([...newMessages, {
    role: "assistant",
    content: assistantContent,
    toolSteps: [...currentToolSteps],
    toolsExpanded: true,
    created_at: Date.now() / 1000,
  }]);
}

// chunk.content 处理不变，但 toolActivity 改为 toolSteps：
if (chunk.content) {
  assistantContent += chunk.content;
  setMessages([...newMessages, {
    role: "assistant",
    content: assistantContent,
    toolSteps: currentToolSteps.length > 0 ? [...currentToolSteps] : undefined,
    toolsExpanded: currentToolSteps.length > 0 ? true : undefined,
    created_at: Date.now() / 1000,
  }]);
}

// done 事件：自动折叠时间轴
if (chunk.done) {
  finalUsage = chunk.usage ? {
    input: chunk.usage.input || 0,
    output: chunk.usage.output || 0,
    cache: chunk.usage.cache || 0,
  } : undefined;
  if (finalUsage) {
    setSessionUsage(prev => ({
      input: prev.input + finalUsage!.input,
      output: prev.output + finalUsage!.output,
      cache: prev.cache + finalUsage!.cache,
    }));
  }
}
```

流式结束后更新最后一条消息时（约第 267 行），把 `toolsExpanded: false` 加进去：

```typescript
setMessages(prev => {
  const msgs = [...prev];
  const last = msgs[msgs.length - 1];
  if (last && last.role === "assistant") {
    msgs[msgs.length - 1] = {
      ...last,
      toolsExpanded: false,   // ← 自动折叠
      usage: finalUsage || last.usage,
      ttft,
    };
  }
  return msgs;
});
```

#### 3. 新建 `web/components/tool-timeline.tsx`

```tsx
"use client";

import { useState } from "react";
import {
  ChevronDown, ChevronRight, Terminal, Globe, FileText,
  Search, Clock, CheckCircle2, XCircle, Loader2
} from "lucide-react";

interface ToolStep {
  tool: string;
  args: string;
  state: "running" | "done" | "error";
  duration_ms?: number;
  result_preview?: string;
}

interface ToolTimelineProps {
  steps: ToolStep[];
  defaultExpanded?: boolean;
}

const TOOL_ICONS: Record<string, React.ReactNode> = {
  shell:            <Terminal className="h-3 w-3" />,
  web_search:       <Search className="h-3 w-3" />,
  web_fetch:        <Globe className="h-3 w-3" />,
  file_read:        <FileText className="h-3 w-3" />,
  file_write:       <FileText className="h-3 w-3" />,
  knowledge_search: <Search className="h-3 w-3" />,
  knowledge_add:    <FileText className="h-3 w-3" />,
};

function StateIcon({ state }: { state: ToolStep["state"] }) {
  if (state === "running") return <Loader2 className="h-3 w-3 animate-spin text-blue-400" />;
  if (state === "done")    return <CheckCircle2 className="h-3 w-3 text-green-400" />;
  return <XCircle className="h-3 w-3 text-red-400" />;
}

export function ToolTimeline({ steps, defaultExpanded = false }: ToolTimelineProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const hasRunning = steps.some(s => s.state === "running");
  const doneCount = steps.filter(s => s.state !== "running").length;

  const summaryNames = [...new Set(steps.map(s => s.tool))].join(", ");

  return (
    <div className="mb-3 rounded-lg border border-border/50 bg-muted/30 overflow-hidden">
      {/* 标题行 */}
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground
                   hover:text-foreground hover:bg-muted/50 transition-colors text-left"
        onClick={() => setExpanded(e => !e)}
      >
        {expanded
          ? <ChevronDown className="h-3 w-3 shrink-0" />
          : <ChevronRight className="h-3 w-3 shrink-0" />}
        <span className="font-medium">
          {hasRunning ? "Running" : `${doneCount} action${doneCount !== 1 ? "s" : ""}`}
        </span>
        <span className="truncate opacity-60">{summaryNames}</span>
        {hasRunning && <Loader2 className="h-3 w-3 animate-spin ml-auto shrink-0 text-blue-400" />}
      </button>

      {/* 展开的时间轴 */}
      {expanded && (
        <div className="px-3 pb-2 space-y-0">
          {steps.map((step, i) => (
            <div key={i} className="flex gap-2 pt-2">
              {/* 竖线 + 状态图标 */}
              <div className="flex flex-col items-center mt-0.5">
                <StateIcon state={step.state} />
                {i < steps.length - 1 && (
                  <div className="w-px flex-1 bg-border/50 mt-1 min-h-[14px]" />
                )}
              </div>

              {/* 工具内容 */}
              <div className="flex-1 min-w-0 pb-1">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-muted-foreground/60">
                    {TOOL_ICONS[step.tool] ?? <Terminal className="h-3 w-3" />}
                  </span>
                  <span className="text-xs font-mono font-medium text-foreground/80">
                    {step.tool}
                  </span>
                  {step.args && (
                    <span className="text-xs text-muted-foreground truncate max-w-[180px]">
                      ({step.args})
                    </span>
                  )}
                  {step.duration_ms !== undefined && step.state !== "running" && (
                    <span className="ml-auto text-[10px] text-muted-foreground/50
                                     flex items-center gap-0.5 shrink-0">
                      <Clock className="h-2.5 w-2.5" />
                      {step.duration_ms < 1000
                        ? `${step.duration_ms}ms`
                        : `${(step.duration_ms / 1000).toFixed(1)}s`}
                    </span>
                  )}
                </div>
                {step.result_preview && step.state !== "running" && (
                  <p className="text-[10px] text-muted-foreground/50 mt-0.5 truncate leading-relaxed">
                    {step.result_preview}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

#### 4. 修改渲染部分（`web/components/chat-view.tsx` 约第 416 行）

```tsx
// 在文件顶部加 import：
import { ToolTimeline } from "@/components/tool-timeline";

// 替换原来的 toolActivity 渲染：
// 删除：
// {msg.toolActivity && (
//   <div className="text-xs text-muted-foreground mb-2 flex items-center gap-1">
//     <span className="animate-pulse">⚡</span>
//     <span>{msg.toolActivity}</span>
//   </div>
// )}

// 替换为：
{msg.toolSteps && msg.toolSteps.length > 0 && (
  <ToolTimeline
    steps={msg.toolSteps}
    defaultExpanded={msg.toolsExpanded ?? false}
  />
)}
```

#### 5. 修改 `web/lib/api.ts` 的 streamChat 类型

```typescript
export async function* streamChat(...): AsyncGenerator<{
  content?: string;
  done?: boolean;
  error?: string;
  model?: string;
  usage?: Record<string, number>;
  tool?: string;
  args?: string;
  state?: string;
  duration_ms?: number;      // 新增
  result_preview?: string;   // 新增
}>
```

---

## 文件改动清单

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `ethan/interface/api.py` | **修改** | `_stream_response()` 加 duration_ms，约 12 行 |
| `web/components/tool-timeline.tsx` | **新建** | 约 90 行 |
| `web/components/chat-view.tsx` | **修改** | 接口扩展 + handleSend 替换 + 渲染替换，约 50 行 |
| `web/lib/api.ts` | **修改** | streamChat yield 类型 +2 字段，约 3 行 |

---

## 交互行为规范

| 状态 | 标题行 | 时间轴内容 |
|------|--------|-----------|
| 工具正在执行 | "Running shell..." + spinner | 展开，当前条有 spinner |
| 所有工具完成，回复流式中 | "N actions tool1, tool2" | 保持展开 |
| 回复流式完成（done 事件） | "N actions" | **自动折叠** |
| 用户点击标题行 | 切换 | toggle |

---

## 验证方法

1. 启动 `ethan serve` 和 Web UI
2. 发送触发工具的消息，如："帮我查一下现在几点"（触发 shell）
3. 观察：时间轴出现并展开，工具执行中有 spinner
4. 工具完成：✅ 图标 + 耗时出现
5. 回复完成：时间轴自动折叠为"1 action"
6. 点击展开/折叠：正常 toggle
7. `npx tsc --noEmit` 无类型错误

```bash
cd /Users/jsongo/code/life/ethan-ai/web && npx tsc --noEmit
```

---

## 注意事项

- `ToolTimeline` 是纯展示组件，折叠状态存 React state，不需要持久化
- 历史消息从数据库恢复时没有 `toolSteps` 字段，历史对话不显示时间轴——这是正确行为
- `result_preview` 后端 `ToolEvent` 里已有（约 60 字），直接用
- 工具名图标映射在 `TOOL_ICONS` 对象里维护，新工具加一行即可
- 不需要修改飞书和 REPL 渠道，这个改动只影响 Web UI
