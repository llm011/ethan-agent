"use client";

import type { StreamChunk } from "@/lib/api";
import type { ToolStep } from "@ethan/shared/components/tool-timeline";
import type { Message, Usage, CardData } from "@ethan/shared/chat/types";
import type { ConsentRequest } from "@ethan/shared/components/consent-dialog";
import type { AskUserRequest } from "@ethan/shared/chat/ask-user-card";

export interface CleanupConfirmRequest {
  request_id: string;
  sessions: Array<{ sessionId: string; title: string; tabCount: number }>;
  timeout?: number;
}

export interface ConsumeStreamActions {
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  setConsentRequest: (req: ConsentRequest | null) => void;
  setCleanupConfirm: (req: CleanupConfirmRequest | null) => void;
  setAskUserRequest: (req: AskUserRequest | null) => void;
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
): Promise<void> {
  const {
    setMessages, setConsentRequest, setCleanupConfirm, setAskUserRequest, setBgPolling,
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
  const cardsCollected: Array<{ type: string; [key: string]: unknown }> = [];
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
      if (chunk.confirm_browser_cleanup) {
        setCleanupConfirm({
          request_id: chunk.request_id || "",
          sessions: chunk.sessions || [],
          timeout: chunk.timeout || 120,
        });
        continue;
      }
      if (chunk.ask_user_request) {
        setAskUserRequest({
          request_id: chunk.request_id || "",
          question: chunk.question || "",
          options: chunk.options || [],
          default: chunk.default || "",
          timeout: chunk.timeout || 20,
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
        const errLine = `⚠️ ${chunk.error}`;
        assistantContent = assistantContent.trim()
          ? `${assistantContent}\n\n---\n${errLine}`
          : errLine;
        break;
      }
      if (chunk.tool && chunk.state === "start") {
        const preToolThought = assistantContent.trim();
        // 不再往 intermediateOutput 累积工具调用前的文本：
        // 这些文本已作为 tool_step.thought 存在 ToolTimeline 里，重复记录会让"过程记录"臃肿。
        // 但保留 assistantContent 展示直到下一个动作完成，让用户能看到思考过程
        currentToolSteps.push({
          tool: chunk.tool, args: chunk.args || "", intent: chunk.intent || undefined, state: "running", id: chunk.id,
          thought: preToolThought || undefined,
          entity_type: chunk.entity_type || undefined,
          entity_id: chunk.entity_id || undefined,
          injected: chunk.injected || undefined,
        });
        setMessages([...baseMessages, {
          role: "assistant", content: assistantContent, thought: assistantThought,
          toolSteps: [...currentToolSteps], toolsExpanded: true, created_at: Date.now() / 1000,
        }]);
      }
      if (chunk.tool && (chunk.state === "done" || chunk.state === "error")) {
        // 动作完成时清除之前的思考文本
        assistantContent = "";
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
            cards: (chunk.cards as ToolStep["cards"]) || currentToolSteps[matchedIdx].cards,
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
        // 工具产出图片时往过程记录记一条简短信息（不记工具详情，只记关键产出）
        if (chunk.cards && Array.isArray(chunk.cards)) {
          cardsCollected.push(...chunk.cards);
          for (const c of chunk.cards) {
            if (c.type === "image") {
              const action = c.source === "file_read" ? "读取" : "下载";
              const loc = c.local_path ? `：\`${c.local_path}\`` : "";
              intermediateOutput += (intermediateOutput ? "\n\n" : "") + `🖼️ ${action}了图片 **${c.title}**（${c.source || ""}）${loc}`;
            }
          }
        }
        if (Array.isArray(chunk.ui)) a2uiSurfaces.push(...chunk.ui);
        if (chunk.mcp_app) mcpAppsCollected.push(chunk.mcp_app);
        setMessages([...baseMessages, {
          role: "assistant", content: assistantContent, thought: assistantThought,
          toolSteps: [...currentToolSteps], toolsExpanded: true, created_at: Date.now() / 1000,
          intermediateOutput: intermediateOutput || undefined,
        }]);
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
      // 顶层 cards 事件（无 tool 字段）：正文兜底补的文件卡片，直播中即时渲染。
      if (chunk.cards && !chunk.tool && Array.isArray(chunk.cards)) {
        cardsCollected.push(...chunk.cards);
        setMessages([...baseMessages, {
          role: "assistant", content: assistantContent, thought: assistantThought,
          toolSteps: currentToolSteps.length > 0 ? [...currentToolSteps] : undefined,
          toolsExpanded: currentToolSteps.length > 0 ? true : undefined,
          created_at: Date.now() / 1000,
          intermediateOutput: intermediateOutput || undefined,
          cards: cardsCollected as any,
        }]);
      }
      if (chunk.done && chunk.usage) {
        finalUsage = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
        if (chunk.ttfb_ms != null) ttfbMs = chunk.ttfb_ms;
        if (chunk.total_ms != null) totalMs = chunk.total_ms;
        if (chunk.message_id != null) messageId = chunk.message_id;
        if (chunk.title) {
          setSessionTitle(chunk.title);
          window.dispatchEvent(new CustomEvent("session:title-updated", { detail: { sessionId: activeSession, title: chunk.title } }));
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
    const errMsg = err instanceof Error ? err.message : "";
    const isNetworkDrop = /load failed|network|aborted|connection|SSE connection dropped/i.test(errMsg);
    if (isNetworkDrop && activeSession) {
      // SSE 静默断开 — 尝试重连活跃 run，失败再拉最终结果
      try {
        const { streamResume } = await import("@/lib/api-chat");
        const resumed = await streamResume(activeSession);
        if (resumed) {
          // 后端仍有活跃 run：续接 SSE 流，继续接收后续事件
          for await (const chunk of resumed) {
            if (chunk.content) assistantContent += chunk.content;
            if (chunk.id && chunk.tool) {
              const toolId = chunk.id;
              setMessages(prev => {
                const msgs = [...prev];
                const last = msgs[msgs.length - 1];
                if (last?.role === "assistant" && last.toolSteps) {
                  const idx = last.toolSteps.findIndex(s => s.id === toolId);
                  if (idx >= 0) {
                    const updated = [...last.toolSteps];
                    updated[idx] = {
                      ...updated[idx],
                      state: chunk.state as "running" | "done" | "error",
                      duration_ms: chunk.duration_ms ?? updated[idx].duration_ms,
                      result_preview: chunk.result_preview ?? updated[idx].result_preview,
                      result_detail: chunk.result_detail ?? updated[idx].result_detail,
                    };
                    msgs[msgs.length - 1] = { ...last, toolSteps: updated };
                  }
                }
                return msgs;
              });
            }
            if (chunk.done) {
              if (chunk.usage) {
                finalUsage = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
              }
              break;
            }
          }
          setBgPolling(null);
          setConsentRequest(null);
          setCleanupConfirm(null);
          setStopping(false);
          setStreaming(false);
          failed = false;
        } else {
          // 无活跃 run：后端已完成，拉最终结果
          const { fetchSession } = await import("@/lib/api-sessions");
          const fresh = await fetchSession(activeSession);
          if (fresh?.messages?.length) {
            const { mapDetailMessages } = await import("@/components/chat/chat-helpers");
            const freshMsgs = mapDetailMessages(fresh);
            setMessages(freshMsgs);
            setBgPolling(null);
            setConsentRequest(null);
            setCleanupConfirm(null);
            setStopping(false);
            setStreaming(false);
            return;
          }
        }
      } catch { /* fallback to show error */ }
    }
    if (failed) {
      const errLine = `⚠️ ${err instanceof Error ? err.message : "连接中断"}`;
      assistantContent = assistantContent.trim()
        ? `${assistantContent}\n\n---\n${errLine}`
        : errLine;
    }
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
        cards: cardsCollected.length > 0 ? cardsCollected as any : undefined,
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
      cards: cardsCollected.length > 0 ? cardsCollected as any : undefined,
      matchedSkills: currentMatchedSkills,
      id: messageId,
      intermediateOutput: intermediateOutput || undefined,
    }];
  });
  setBgPolling(null);
  setStopping(false);
  setStreaming(false);
  setConsentRequest(null);
  setCleanupConfirm(null);
}
