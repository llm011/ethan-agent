import type { StreamChunk } from "@/lib/api";
import type { ToolStep } from "@ethan/shared/components/tool-timeline";
import type { Message, Usage } from "@ethan/shared/chat/types";
import type { ConsentRequest } from "@ethan/shared/components/consent-dialog";

export interface ConsumeStreamActions {
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  setConsentRequest: (req: ConsentRequest | null) => void;
  setBgPolling: (msg: string | null) => void;
  setSessionTitle: (title: string) => void;
  setSessionUsage: React.Dispatch<React.SetStateAction<Usage>>;
  setStopping: (v: boolean) => void;
  setStreaming: (v: boolean) => void;
  activeSession: string | null;
}

// 消费一条 SSE 事件流，增量更新最后一条 assistant 消息，结束后定稿。
// 首次发送（streamChat）与刷新重连（streamResume）共用此逻辑。
// baseMessages = assistant 之前的全部消息（含用户那句）；trackTtft 仅首发为 true。
export async function consumeStream(
  stream: AsyncGenerator<StreamChunk>,
  baseMessages: Message[],
  actions: ConsumeStreamActions,
  trackTtft = false,
): Promise<{ failed: boolean }> {
  const {
    setMessages, setConsentRequest, setBgPolling,
    setSessionTitle, setSessionUsage, setStopping, setStreaming,
    activeSession,
  } = actions;

  let failed = false;
  let assistantContent = "";
  let intermediateOutput = "";
  const assistantThought = "";
  const currentToolSteps: ToolStep[] = [];
  let currentMatchedSkills: { name: string; is_default?: boolean }[] | undefined;
  const a2uiSurfaces: unknown[] = [];
  const mcpAppsCollected: Array<{ uri: string; data?: Record<string, unknown>; html?: string; csp?: Record<string, string[]> }> = [];
  const sendTime = Date.now();
  let ttft: number | undefined;
  let ttfbMs: number | undefined;
  let totalMs: number | undefined;
  let messageId: number | undefined;
  let finalUsage: Usage | undefined;
  setMessages([...baseMessages, { role: "assistant", content: "", created_at: Date.now() / 1000 }]);

  try {
    for await (const chunk of stream) {
      if (trackTtft && ttft === undefined) ttft = Date.now() - sendTime;

      if (chunk.consent_request) {
        setConsentRequest({
          request_id: chunk.request_id || "",
          tool: chunk.tool || "",
          description: chunk.description || "",
          detail: chunk.detail,
        });
        continue;
      }
      if (chunk.skills_matched) {
        currentMatchedSkills = chunk.skills_matched;
        continue;
      }
      if (chunk.background_polling) {
        setBgPolling(chunk.polling_message || "\u{1f4e1} 后台任务运行中...");
        continue;
      }
      if (chunk.new_message) {
        setBgPolling(null);
        setMessages(prev => [...prev, {
          role: "assistant",
          content: chunk.content || "",
          created_at: Date.now() / 1000,
        }]);
        continue;
      }
      if (chunk.heartbeat) {
        const elapsed = chunk.elapsed || 0;
        const mins = Math.floor(elapsed / 60);
        const secs = elapsed % 60;
        const timeStr = mins > 0 ? `${mins} 分 ${secs} 秒` : `${secs} 秒`;
        const statusNote = `_⏳ 任务仍在运行中，已用时 ${timeStr}，请稍候…_`;
        setMessages([...baseMessages, {
          role: "assistant",
          content: assistantContent || statusNote,
          thought: assistantThought,
          toolSteps: currentToolSteps.length > 0 ? [...currentToolSteps] : undefined,
          toolsExpanded: currentToolSteps.length > 0 ? true : undefined,
          created_at: Date.now() / 1000,
          intermediateOutput: intermediateOutput || undefined,
        }]);
        continue;
      }
      if (chunk.error) {
        failed = true;
        const errLine = `⚠️ ${chunk.error}`;
        assistantContent = assistantContent.trim()
          ? `${assistantContent}\n\n---\n${errLine}`
          : errLine;
        break;
      }
      if (chunk.tool && chunk.state === "start") {
        const preToolThought = assistantContent.trim();
        if (preToolThought) {
          intermediateOutput += (intermediateOutput ? "\n\n" : "") + preToolThought;
        }
        assistantContent = "";
        currentToolSteps.push({
          tool: chunk.tool, args: chunk.args || "", intent: chunk.intent || undefined, state: "running", id: chunk.id,
          thought: preToolThought || undefined,
          entity_type: chunk.entity_type || undefined,
          entity_id: chunk.entity_id || undefined,
        });
        setMessages([...baseMessages, {
          role: "assistant", content: assistantContent, thought: assistantThought,
          toolSteps: [...currentToolSteps], toolsExpanded: true, created_at: Date.now() / 1000,
          intermediateOutput: intermediateOutput || undefined,
        }]);
      }
      if (chunk.tool && (chunk.state === "done" || chunk.state === "error")) {
        let matchedIdx = -1;
        if (chunk.id) {
          for (let i = currentToolSteps.length - 1; i >= 0; i--) {
            if (currentToolSteps[i].id === chunk.id && currentToolSteps[i].state === "running") {
              matchedIdx = i; break;
            }
          }
        }
        if (matchedIdx < 0) {
          for (let i = currentToolSteps.length - 1; i >= 0; i--) {
            if (currentToolSteps[i].tool === chunk.tool && currentToolSteps[i].state === "running") {
              matchedIdx = i; break;
            }
          }
        }
        if (matchedIdx >= 0) {
          currentToolSteps[matchedIdx] = {
            ...currentToolSteps[matchedIdx],
            state: chunk.state as "done" | "error",
            duration_ms: chunk.duration_ms,
            result_preview: chunk.result_preview,
            result_detail: chunk.result_detail,
            entity_type: chunk.entity_type || currentToolSteps[matchedIdx].entity_type,
            entity_id: chunk.entity_id || currentToolSteps[matchedIdx].entity_id,
            sub_steps: chunk.sub_steps?.map((s) => ({
              tool: s.tool,
              args: s.args,
              state: s.state as "running" | "done" | "error",
              duration_ms: s.duration_ms ?? undefined,
              result_preview: s.result_preview,
            })),
          };
        }
        setMessages([...baseMessages, {
          role: "assistant", content: assistantContent, thought: assistantThought,
          toolSteps: [...currentToolSteps], toolsExpanded: true, created_at: Date.now() / 1000,
          intermediateOutput: intermediateOutput || undefined,
        }]);
      }
      if (chunk.tool && (chunk.state === "done" || chunk.state === "error") && chunk.ui && Array.isArray(chunk.ui)) {
        a2uiSurfaces.push(...chunk.ui);
      }
      if (chunk.tool && (chunk.state === "done" || chunk.state === "error") && chunk.mcp_app) {
        mcpAppsCollected.push(chunk.mcp_app);
      }
      if (chunk.content) {
        setBgPolling(null);
        assistantContent += chunk.content;
        setMessages([...baseMessages, {
          role: "assistant", content: assistantContent, thought: assistantThought,
          toolSteps: currentToolSteps.length > 0 ? [...currentToolSteps] : undefined,
          toolsExpanded: currentToolSteps.length > 0 ? true : undefined,
          created_at: Date.now() / 1000,
          intermediateOutput: intermediateOutput || undefined,
        }]);
      }
      if (chunk.done && chunk.usage) {
        finalUsage = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
        if (chunk.ttfb_ms != null) ttfbMs = chunk.ttfb_ms;
        if (chunk.total_ms != null) totalMs = chunk.total_ms;
        if (chunk.message_id != null) messageId = chunk.message_id;
        if (chunk.title) {
          setSessionTitle(chunk.title);
          window.dispatchEvent(new CustomEvent("session:title-updated", {
            detail: { sessionId: activeSession, title: chunk.title }
          }));
        }
        setSessionUsage(prev => ({
          input: prev.input + finalUsage!.input,
          output: prev.output + finalUsage!.output,
          cache: prev.cache + finalUsage!.cache,
        }));
      }
      if (chunk.done) {
        setBgPolling(null);
      }
      if (chunk.stopped) {
        if (!assistantContent.trimEnd().endsWith("（已停止）")) {
          assistantContent = assistantContent.trim()
            ? `${assistantContent}\n\n_（已停止）_`
            : "_（已停止）_";
        }
        if (chunk.usage) {
          finalUsage = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
        }
        break;
      }
    }
  } catch (err) {
    failed = true;
    const errLine = `⚠️ ${err instanceof Error ? err.message : "连接中断"}`;
    assistantContent = assistantContent.trim()
      ? `${assistantContent}\n\n---\n${errLine}`
      : errLine;
  }

  setMessages(prev => {
    const msgs = [...prev];
    const last = msgs[msgs.length - 1];
    if (last && last.role === "assistant") {
      msgs[msgs.length - 1] = {
        ...last,
        content: assistantContent,
        thought: assistantThought,
        toolsExpanded: false,
        usage: finalUsage || last.usage,
        ttft: ttft ?? last.ttft,
        ttfb_ms: ttfbMs ?? last.ttfb_ms,
        total_ms: totalMs ?? last.total_ms,
        a2ui: a2uiSurfaces.length > 0 ? a2uiSurfaces : undefined,
        mcpApps: mcpAppsCollected.length > 0 ? mcpAppsCollected : undefined,
        matchedSkills: currentMatchedSkills,
        id: messageId ?? last.id,
        intermediateOutput: intermediateOutput || undefined,
      };
      return msgs;
    }
    return [...baseMessages, {
      role: "assistant",
      content: assistantContent,
      thought: assistantThought,
      created_at: Date.now() / 1000,
      usage: finalUsage,
      ttft,
      ttfb_ms: ttfbMs,
      total_ms: totalMs,
      a2ui: a2uiSurfaces.length > 0 ? a2uiSurfaces : undefined,
      mcpApps: mcpAppsCollected.length > 0 ? mcpAppsCollected : undefined,
      matchedSkills: currentMatchedSkills,
      id: messageId,
      intermediateOutput: intermediateOutput || undefined,
    }];
  });
  setBgPolling(null);
  setConsentRequest(null);
  setStopping(false);
  setStreaming(false);

  return { failed };
}
