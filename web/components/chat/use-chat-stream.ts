"use client";

import type { StreamChunk } from "@/lib/api";
import type { ToolStep } from "@ethan/shared/components/tool-timeline";
import type { Message, Usage, CardData } from "@ethan/shared/chat/types";
import type { ConsentRequest } from "@ethan/shared/components/consent-dialog";
import type { AskUserRequest } from "@ethan/shared/chat/ask-user-card";
import type { WaitForUserRequest } from "@ethan/shared/chat/wait-for-user-card";

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
  setWaitForUserRequest: (req: WaitForUserRequest | null) => void;
  setBgPolling: (msg: string | null) => void;
  setSessionTitle: (title: string) => void;
  setSessionUsage: React.Dispatch<React.SetStateAction<Usage>>;
  setStopping: (v: boolean) => void;
  setStreaming: (v: boolean) => void;
  setPendingInjected: React.Dispatch<React.SetStateAction<{ id: string; content: string }[]>>;
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
  signal?: AbortSignal,
): Promise<void> {
  const {
    setMessages, setConsentRequest, setCleanupConfirm, setAskUserRequest, setWaitForUserRequest, setBgPolling,
    setSessionTitle, setSessionUsage, setStopping, setStreaming, setPendingInjected,
    activeSession,
  } = actions;

  let failed = false;
  let assistantContent = "";
  let lastError: string | undefined;
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
  let finalModel: string | undefined;
  setMessages([...baseMessages, { role: "assistant", content: "", created_at: Date.now() / 1000, model: finalModel }]);

  let _rafId: number | null = null;
  const buildMsg = (extra?: Partial<Message>): Message => ({
    role: "assistant" as const,
    content: assistantContent,
    thought: assistantThought,
    toolSteps: currentToolSteps.length > 0 ? [...currentToolSteps] : undefined,
    toolsExpanded: currentToolSteps.length > 0 ? true : undefined,
    created_at: Date.now() / 1000,
    model: finalModel,
    intermediateOutput: intermediateOutput || undefined,
    ...extra,
  });
  const flushAssistant = (extra?: Partial<Message>) => {
    const msg = buildMsg(extra);
    setMessages(prev => {
      if (!prev.length || prev[prev.length - 1]?.role !== "assistant") return prev;
      const next = [...prev];
      next[next.length - 1] = msg;
      return next;
    });
  };
  const scheduleFlush = () => {
    if (_rafId !== null) return;
    _rafId = requestAnimationFrame(() => { _rafId = null; flushAssistant(); });
  };
  const cancelScheduledFlush = () => {
    if (_rafId !== null) { cancelAnimationFrame(_rafId); _rafId = null; }
  };

  try {
    for await (const chunk of stream) {
      if (trackTtft && ttft === undefined) ttft = Date.now() - sendTime;

      // 模型在回复一开始就被后端 emit，立即记下并刷新气泡底部（与开始时间并列显示），
      // 不再等到 done 事件才出现。done 事件也带 model（error/stopped 不带），但各事件要走自己的分支逻辑，
      // 所以这里只对「纯 model 事件」单独重渲染，其他情况交给下方各分支 + 定稿。
      // 用白名单判定：除 model 外无任何其它字段才算纯 model 事件，
      // 避免以后新增字段（如带上 consent_request）时被黑名单漏判而 continue 跳过。
      if (chunk.model) {
        finalModel = chunk.model;
        const onlyModel = Object.keys(chunk).every(k => k === "model");
        if (onlyModel) {
          setMessages(prev =>
            prev.length && prev[prev.length - 1]?.role === "assistant"
              ? prev.map((m, i) => (i === prev.length - 1 ? { ...m, model: finalModel } : m))
              : prev,
          );
          continue;
        }
      }

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
      if (chunk.wait_for_user_request) {
        setWaitForUserRequest({
          request_id: chunk.request_id || "",
          prompt: chunk.prompt || "",
          input_type: (chunk.input_type as "confirm" | "text") || "confirm",
          placeholder: chunk.placeholder || "",
          confirm_label: chunk.confirm_label || "已完成",
          cancel_label: chunk.cancel_label || "取消",
          timeout: chunk.timeout || 300,
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
      if (chunk.injected_added) {
        // 新补充一条待处理信息（含断线重连回放）：按 id 去重
        const item = chunk.injected_added;
        setPendingInjected(prev => (prev.some(p => p.id === item.id) ? prev : [...prev, item]));
        continue;
      }
      if (chunk.injected_removed) {
        // 用户在待处理区删除了一条（处理前）
        setPendingInjected(prev => prev.filter(p => p.id !== chunk.injected_removed));
        continue;
      }
      if (chunk.injected && !chunk.tool) {
        // 被模型消费：从待处理区移除（drain 一次性取走全部，按内容匹配；
        // 注意 tool start 事件也带 injected 字段，需排除）
        const consumed = new Set(chunk.injected);
        setPendingInjected(prev => prev.filter(p => !consumed.has(p.content)));
        continue;
      }
      if (chunk.heartbeat) {
        const elapsed = chunk.elapsed || 0;
        const mins = Math.floor(elapsed / 60);
        const secs = elapsed % 60;
        const timeStr = mins > 0 ? `${mins} 分 ${secs} 秒` : `${secs} 秒`;
        const statusNote = `_⏳ 任务仍在运行中，已用时 ${timeStr}，请稍候…_`;
        flushAssistant({ content: assistantContent || statusNote });
        continue;
      }
      if (chunk.error) {
        failed = true;
        // 错误原因走独立 error 字段（message-bubble 的「已中断」提示条读取），
        // 不混入 content 正文，避免把错误文案当正常回复渲染、同一信息展示两遍。
        lastError = chunk.error;
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
        cancelScheduledFlush();
        flushAssistant();
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
        cancelScheduledFlush();
        flushAssistant();
      }
      if (chunk.content) {
        setBgPolling(null);
        assistantContent += chunk.content;
        scheduleFlush();
      }
      // 顶层 cards 事件（无 tool 字段）：正文兜底补的文件卡片，直播中即时渲染。
      if (chunk.cards && !chunk.tool && Array.isArray(chunk.cards)) {
        cardsCollected.push(...chunk.cards);
        cancelScheduledFlush();
        flushAssistant({ cards: cardsCollected as unknown as CardData[] });
      }
      if (chunk.done && chunk.usage) {
        finalUsage = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
        if (chunk.ttfb_ms != null) ttfbMs = chunk.ttfb_ms;
        if (chunk.total_ms != null) totalMs = chunk.total_ms;
        if (chunk.message_id != null) messageId = chunk.message_id;
        if (chunk.model) finalModel = chunk.model;
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
    if ((err as { name?: string })?.name === "AbortError") {
      // 切换会话/发新消息 abort 旧流：清理残留的交互卡片状态，避免新会话误显示
      cancelScheduledFlush();
      setConsentRequest(null);
      setCleanupConfirm(null);
      setAskUserRequest(null);
      setWaitForUserRequest(null);
      setPendingInjected([]);
      return;
    }
    const errMsg = err instanceof Error ? err.message : "";
    const isNetworkDrop = /load failed|network|connection|SSE connection dropped/i.test(errMsg);
    if (isNetworkDrop && activeSession) {
      // SSE 静默断开 — 尝试重连活跃 run，失败再拉最终结果
      try {
        if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
        const { streamResume } = await import("@/lib/api-chat");
        const resumed = await streamResume(activeSession, signal);
        if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
        if (resumed) {
          // 后端仍有活跃 run：续接 SSE 流，继续接收后续事件
          for await (const chunk of resumed) {
            // 断线可能发生在首个事件送达之前，model 事件会在重连后才到，这里同样记下来，
            // 定稿时写入气泡（model: finalModel ?? last.model），避免重连后气泡不显示模型。
            if (chunk.model) finalModel = chunk.model;
            // 重连后后端会回放仍在 pending 的交互事件（consent/ask_user/wait_for_user），
            // 必须与主分支对齐处理，否则断线重连后卡片不再弹出、agent 卡在等待直到超时。
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
            if (chunk.wait_for_user_request) {
              setWaitForUserRequest({
                request_id: chunk.request_id || "",
                prompt: chunk.prompt || "",
                input_type: (chunk.input_type as "confirm" | "text") || "confirm",
                placeholder: chunk.placeholder || "",
                confirm_label: chunk.confirm_label || "已完成",
                cancel_label: chunk.cancel_label || "取消",
                timeout: chunk.timeout || 300,
              });
              continue;
            }
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
          setAskUserRequest(null);
          setWaitForUserRequest(null);
          setPendingInjected([]);
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
            setAskUserRequest(null);
            setWaitForUserRequest(null);
            setPendingInjected([]);
            setStopping(false);
            setStreaming(false);
            return;
          }
        }
      } catch (reconnectErr) {
        // reconnect 中被 abort：与顶层 AbortError 同处理
        if ((reconnectErr as { name?: string })?.name === "AbortError") {
          setConsentRequest(null);
          setCleanupConfirm(null);
          setAskUserRequest(null);
          setWaitForUserRequest(null);
          return;
        }
        failed = true;
      }
    }
    if (failed) {
      lastError = lastError || (err instanceof Error ? err.message : "连接中断");
    }
  }

  cancelScheduledFlush();
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
        model: finalModel ?? last.model,
        error: lastError || undefined,
      };
      return msgs;
    }
    return [...prev, {
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
      model: finalModel,
      error: lastError || undefined,
    }];
  });
  setBgPolling(null);
  setStopping(false);
  setStreaming(false);
  setConsentRequest(null);
  setCleanupConfirm(null);
  setAskUserRequest(null);
  setWaitForUserRequest(null);
  // run 结束：待处理补充信息区清空（后端同样在 run 收尾清空 DB 镜像）
  setPendingInjected([]);
}
