"use client";

import type { StreamChunk } from "@/lib/api";
import type { ToolStep } from "@ethan/shared/components/tool-timeline";
import type { Message, Usage } from "@ethan/shared/chat/types";
import type { ConsentRequest } from "@ethan/shared/components/consent-dialog";
import type { AskUserRequest } from "@ethan/shared/chat/ask-user-card";
import type { WaitForUserRequest } from "@ethan/shared/chat/wait-for-user-card";
import { MESSAGE_PAGE_SIZE, makeTempId, replaceTailKeepOlder } from "@ethan/shared/chat/history";

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
  /**
   * 该流所属的会话是否仍是当前**正在显示**的会话。
   *
   * 必须是「实时」判断（调用方用 ref 读取当前会话，而不是把值捕获进闭包），
   * 否则流开始时是 true、切走后仍是 true，守卫就失效了。
   */
  isSessionActive: () => boolean;
}

/**
 * 给所有「**按会话展示**的状态写入」套一层会话守卫。
 *
 * 为什么需要它（真实 bug）：用户在会话 A 里发 query，回复还在流式输出时切到会话 B，
 * A 的流片段会写进 B 的消息列表 —— 因为：
 *  1. `for await` 循环每收到一个 chunk 就 `setMessages`，全程没有任何「这条流还属于
 *     当前会话吗」的判断；
 *  2. 切会话时的 `abort()` 是**异步**生效的（`reader.read()` 要到下一个 tick 才 reject），
 *     已经 yield 出来、正在被消费的 chunk 仍会走完这一轮写入；
 *  3. 与此同时新会话已经在 `setMessages([])` + 拉自己的历史。三者交错，旧内容就落到新会话里。
 *
 * 修法不是「早点 abort」（那只是缩小窗口，仍有竞态），而是**每次写入前重新确认身份**：
 * 只要流所属会话已不是当前显示的会话，就整体丢弃这次写入。
 *
 * 适用范围是「按会话展示」的全部状态，不只消息列表：标题、token 用量、待处理补充信息
 * 同样是当前会话的展示态，旧流一样会把 A 的写进 B（A 的标题盖掉 B 的、用量加到 B 头上）。
 * 反过来，全局态（streaming / stopping / 授权弹窗）和按会话 id 定位的侧边栏事件不受守卫约束。
 *
 * 丢弃是安全的：切走时新会话会重新拉历史，切回时原会话也会从 DB 重新加载，
 * 后端落库的内容不会丢。
 */
function guardedWrite(isSessionActive: () => boolean, write: () => void): void {
  if (!isSessionActive()) return;
  write();
}

// 把本地刚发出的 user 消息补回后端返回的消息列表，避免后端漏存时用户那条
// query 从界面上消失（用户反馈：回复失败后连自己发的 query 都找不回）。
//
// 按 content 的**出现次数差额**补：本地有几条、后端有几条，差多少补多少。
// 两个理由：
//  1. 后端正常落库的历史消息，本地与后端条数一致 → 差额为 0，不会被复活
//     （早前版本只看「本地末尾那段」，会漏掉更早出现的重复 query）。
//  2. 同一会话连发两条完全相同的 query（重试、复制粘贴、队列 drain）时，后端可能
//     只落了第一条。若只判「这个 content 出现过没有」，第二条会被当成已存在而不补，
//     query 照样消失——正是本函数要修的那个 bug 本身。
export function mergeMissingUserMessages(local: Message[], fromServer: Message[]): Message[] {
  const countUserContent = (msgs: Message[], content: string) =>
    msgs.filter((m) => m.role === "user" && m.content === content).length;

  // 逐条扫描本地的 user 消息，累计「该 content 本地出现到第几次」，
  // 后端条数不够这么多就说明这一条没落库，需要补。
  const seen = new Map<string, number>();
  const missing: Message[] = [];
  for (const m of local) {
    if (m.role !== "user" || !m.content) continue;
    const nth = (seen.get(m.content) ?? 0) + 1;
    seen.set(m.content, nth);
    if (countUserContent(fromServer, m.content) < nth) missing.push(m);
  }
  if (missing.length === 0) return fromServer;

  return [...fromServer, ...missing];
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
    activeSession, isSessionActive,
  } = actions;

  // 本函数内所有「按会话展示」的写入都必须过守卫：消息列表 / 标题 / 用量 / 补充信息。
  // 中途切会话后旧流的在途 chunk 要整体丢弃，否则会污染新会话（见 guardedWrite 注释）。
  const writeActive = (write: () => void) => guardedWrite(isSessionActive, write);
  const writeMsgs = (next: React.SetStateAction<Message[]>) => writeActive(() => setMessages(next));

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
  // 占位 assistant 气泡：先生成一个临时 id，让气泡从第一帧起就有稳定 React key
  // （分页后列表会整体前插，用下标当 key 会错位）。后端落库后 promoteMessageId 提升成真实 id。
  const placeholderId = makeTempId();
  writeMsgs([...baseMessages, { role: "assistant", content: "", created_at: Date.now() / 1000, model: finalModel, id: placeholderId }]);

  let _rafId: number | null = null;
  let _flushTimer: ReturnType<typeof setTimeout> | null = null;
  // 流式期间这条助手消息的稳定 id。
  //
  // 必须是**一条流一个**：占位气泡从第一帧起就拿它当 React key，后端落库后再由
  // 定稿提升成真实数字 id。中途任何一次重建都不能把它丢掉 —— 见下面 flushAssistant
  // 的注释（key 一塌，列表就会重挂甚至撞车出重复气泡）。
  let liveId: number | string = placeholderId;
  const buildMsg = (extra?: Partial<Message>): Message => ({
    role: "assistant" as const,
    content: assistantContent,
    thought: assistantThought,
    toolSteps: currentToolSteps.length > 0 ? [...currentToolSteps] : undefined,
    toolsExpanded: currentToolSteps.length > 0 ? true : undefined,
    created_at: Date.now() / 1000,
    model: finalModel,
    intermediateOutput: intermediateOutput || undefined,
    id: liveId,
    ...extra,
  });
  /**
   * 把当前累积状态刷进占位气泡。
   *
   * 语义是「**就地更新**最后一条 assistant 消息」，不是「用一条新消息替换它」。
   * 差别全在 id 上：`buildMsg` 重建出来的对象即使带 `id: liveId`，也不能保证
   * 覆盖到所有字段 —— 早前这里直接 `next[next.length - 1] = msg`，而 `buildMsg`
   * 根本不带 `id`，于是**正文到达之前**的任何一次 flush（心跳「任务仍在运行中…」、
   * 工具 start/done、顶层 cards）都会把占位气泡的 `tmp:xxx` 抹成 `undefined`。
   *
   * 后果（用户现象：同一条回复出现两份）：
   *  - MessageList 的 `key={msg.id ?? \`idx-${startIdx + i}\`}` 退化成下标 key，
   *    占位气泡被 React 卸载重建（markdown 重解析、代码块重高亮、滚动锚点丢失）；
   *  - 下标 key 在同一列表里可能撞车，React 把两个兄弟节点折叠/重复渲染 ——
   *    就是「同一条回复渲染了两次」。刷新后从 DB 重新拉历史，id 回来、重复消失，
   *    与「点刷新就好了」的现象吻合；
   *  - 丢失不可恢复：后续每次 flush 都基于上一次结果再替换，占位 id 再也回不来；
   *    定稿的 `id: messageId ?? last.id` 此时 `last.id` 已是 `undefined`，而后端在
   *    「无工具无正文」等路径下 `done` 不带 `message_id`，定稿后 id 仍是空。
   *
   * 所以这里沿用上一条消息的 id（`liveId`），保证「同一条回复」在整个生命周期里
   * 始终是同一个 key。后端给出真实 id 时由定稿路径提升，并同步写回 `liveId`，
   * 避免后续 flush 把真实 id 又退回临时 id。
   */
  const flushAssistant = (extra?: Partial<Message>) => {
    writeMsgs(prev => {
      const next = [...prev];
      // 必须按 **id** 定位本次流自己的那条气泡，不能假设「最后一条就是它」。
      // `chunk.new_message` 会往列表末尾追加一条旁路消息（见下面 new_message 分支），
      // 此时最后一条已经不是本流的占位气泡了；若仍按「末位」更新，就会：
      //   1. 把占位气泡的 `liveId` 盖到那条旁路消息上 → 两条兄弟节点 **同 key**
      //      （React 折叠/重复渲染，正是本 PR 要修的现象）；
      //   2. 本流已累积的正文被写进旁路消息，真正的占位气泡则永远停在旧内容上。
      const idx = next.findIndex(m => m.role === "assistant" && m.id === liveId);
      if (idx >= 0) {
        next[idx] = buildMsg(extra);
        return next;
      }
      next.push(buildMsg(extra));
      return next;
    });
  };
  // 流式刷新的节流窗口。
  //
  // 以前是每个 rAF 刷一次（≈60fps）：每次 setMessages 都会重渲染整个 ChatView
  // 及其子树（MessageList / markdown 重新解析 / 代码块重新高亮），长消息下
  // 每帧的 markdown 重解析开销随内容增长，是「流式输出时整机发卡」的主因。
  // 人眼对 60fps 与 ~20fps 的逐字输出几乎无感，但渲染次数降到 1/3。
  const FLUSH_INTERVAL_MS = 50;
  let _lastFlushAt = 0;

  const scheduleFlush = () => {
    if (_flushTimer !== null || _rafId !== null) return;
    const elapsed = Date.now() - _lastFlushAt;
    if (elapsed >= FLUSH_INTERVAL_MS) {
      _lastFlushAt = Date.now();
      _rafId = requestAnimationFrame(() => { _rafId = null; flushAssistant(); });
      return;
    }
    _flushTimer = setTimeout(() => {
      _flushTimer = null;
      _lastFlushAt = Date.now();
      flushAssistant();
    }, FLUSH_INTERVAL_MS - elapsed);
  };
  const cancelScheduledFlush = () => {
    if (_rafId !== null) { cancelAnimationFrame(_rafId); _rafId = null; }
    if (_flushTimer !== null) { clearTimeout(_flushTimer); _flushTimer = null; }
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
          writeMsgs(prev =>
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
        // 旁路消息必须带**自己的** id：不生成的话它是无 id 的，会与占位气泡一起退化成
        // 下标 key（同 key → 重复渲染）；更要命的是不能拿占位气泡的 id（会撞成同 key）。
        writeMsgs(prev => [...prev, {
          role: "assistant",
          content: chunk.content || "",
          created_at: Date.now() / 1000,
          id: makeTempId(),
        }]);
        continue;
      }
      if (chunk.injected_added) {
        // 新补充一条待处理信息（含断线重连回放）：按 id 去重
        const item = chunk.injected_added;
        writeActive(() => setPendingInjected(prev => (prev.some(p => p.id === item.id) ? prev : [...prev, item])));
        continue;
      }
      if (chunk.injected_removed) {
        // 用户在待处理区删除了一条（处理前）
        writeActive(() => setPendingInjected(prev => prev.filter(p => p.id !== chunk.injected_removed)));
        continue;
      }
      if (chunk.injected && !chunk.tool) {
        // 被模型消费：从待处理区移除（drain 一次性取走全部，按内容匹配；
        // 注意 tool start 事件也带 injected 字段，需排除）
        const consumed = new Set(chunk.injected);
        writeActive(() => setPendingInjected(prev => prev.filter(p => !consumed.has(p.content))));
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
          gen_ms: chunk.gen_ms ?? undefined,
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
            gen_ms: chunk.gen_ms ?? undefined,
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
        flushAssistant({ cards: cardsCollected as unknown as Message["cards"] });
      }
      if (chunk.done && chunk.usage) {
        finalUsage = { input: chunk.usage.input || 0, output: chunk.usage.output || 0, cache: chunk.usage.cache || 0 };
        if (chunk.ttfb_ms != null) ttfbMs = chunk.ttfb_ms;
        if (chunk.total_ms != null) totalMs = chunk.total_ms;
        if (chunk.message_id != null) messageId = chunk.message_id;
        if (chunk.model) finalModel = chunk.model;
        if (chunk.title) {
          // 只更新「当前会话」的标题栏；侧边栏那条事件按会话 id 定位，切走后照样要发
          writeActive(() => setSessionTitle(chunk.title!));
          window.dispatchEvent(new CustomEvent("session:title-updated", { detail: { sessionId: activeSession, title: chunk.title } }));
        }
        writeActive(() => setSessionUsage(prev => ({
          input: prev.input + finalUsage!.input,
          output: prev.output + finalUsage!.output,
          cache: prev.cache + finalUsage!.cache,
        })));
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
      // 切换会话/发新消息 abort 旧流：清理残留的交互卡片状态，避免新会话误显示。
      // 授权/清理弹窗是全局态，直接清；待处理补充信息是按会话展示的，走守卫 ——
      // 切会话时新会话自己会从后端加载它那份，这里不该把新会话的擦掉。
      cancelScheduledFlush();
      setConsentRequest(null);
      setCleanupConfirm(null);
      setAskUserRequest(null);
      setWaitForUserRequest(null);
      writeActive(() => setPendingInjected([]));
      // 被 abort（切会话/新发送抢占）同样要收尾 streaming：早前这里是裸 return，
      // 跳过了函数末尾的 setStreaming(false)，streamingRef 会永久留在 true，
      // 之后每次 handleSend 都在守卫处静默返回，表现为「发了消息没反应」。
      setStopping(false);
      setStreaming(false);
      return;
    }
    const errMsg = err instanceof Error ? err.message : "";
    // 超时也要走重连：断网时 socket 半死，fetchWithTimeout 会抛「请求超时（Ns）」，
    // 若不算作掉线就会直接判失败，白白丢掉后面的已生成内容。
    const isNetworkDrop = /load failed|network|connection|SSE connection dropped|请求超时/i.test(errMsg);
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
              writeMsgs(prev => {
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
                      gen_ms: chunk.gen_ms ?? updated[idx].gen_ms,
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
          writeActive(() => setPendingInjected([]));
          setStopping(false);
          setStreaming(false);
          failed = false;
        } else {
          // 无活跃 run：后端已完成，拉最终结果。
          // 只拉最近一页而不是全量：长会话全量拉要好几秒，而这里只是为了定稿
          // 最后一条 assistant 消息，更早的历史前端已经按页加载过了。
          const { fetchSessionPage } = await import("@/lib/api-sessions");
          const fresh = await fetchSessionPage(activeSession, { limit: MESSAGE_PAGE_SIZE });
          if (fresh?.messages?.length) {
            const { mapDetailMessages } = await import("@/components/chat/chat-helpers");
            const freshMsgs = mapDetailMessages(fresh);
            // 后端可能压根没存下用户刚发的那条 query（如建 agent 阶段就失败，
            // 或落库异常）。若这里直接用后端结果整表替换，用户会看到自己发的
            // 消息"凭空消失"。因此把 baseMessages 里后端缺失的 user 消息补回去。
            //
            // 关键：不能整表替换 —— 用户上滚翻出来的更早几页不在这一页里，
            // 直接 setMessages(这一页) 会让它们凭空消失。
            //
            // 合并方向：把「已加载的更早历史」拼到「刚拉到的一页」前面。
            // - freshMsgs 是权威的最近一页（含刚定稿的 assistant 真实 id），放在后面
            // - prev 里早于这一页的部分保留在最前面；prependOlderMessages 按 id 去重，
            //   与这一页重叠的那段会用 freshMsgs 的版本
            const mergedMsgs = mergeMissingUserMessages(baseMessages, freshMsgs);
            writeMsgs(prev => replaceTailKeepOlder(prev, mergedMsgs));
            setBgPolling(null);
            setConsentRequest(null);
            setCleanupConfirm(null);
            setAskUserRequest(null);
            setWaitForUserRequest(null);
            writeActive(() => setPendingInjected([]));
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
          // 同上：abort 也要收尾，别把 streaming 留在 true。
          setStopping(false);
          setStreaming(false);
          return;
        }
        failed = true;
      }
    }
    if (failed) {
      lastError = lastError || (err instanceof Error ? err.message : "连接中断");
    }
  }

  // 先落定稿再取消：反过来会留下一个「读到旧闭包状态、在定稿之后才执行」的定时 flush，
  // 把刚写好的定稿覆盖掉（表现为最后一条消息偶尔回退到中途状态）。
  //
  // 定稿时按 id 定位气泡，并把 id 落到 liveId（后端给了真实 id 就提升，后续迟到的
  // flush 也不会退回临时 id；没给就保留占位 id，**绝不能写成 undefined**）。
  //
  // 提升必须发生在**拿到数组之后、就地改写那条气泡时**：`liveId` 与数组里那条气泡的
  // `id` 是同一份身份，若提前把 `liveId` 改成真实 id，`findIndex` 就再也匹配不到仍带
  // 临时 id 的占位气泡，会走 push 分支**凭空多出一条**（表现为同一条回复两个气泡）。
  writeMsgs(prev => {
    const msgs = [...prev];
    // 与 flushAssistant 同理：只能按 **id** 定位本次流自己的那条气泡。
    // `chunk.new_message` 会在末尾追加旁路消息，若这里仍按「末位」定稿，就会把
    // 主流的正文 / 真实 message_id 写到旁路消息上，真正的占位气泡则永远停在空内容上。
    const idx = msgs.findIndex(m => m.role === "assistant" && m.id === liveId);
    if (idx >= 0) {
      const last = msgs[idx];
      const settledId = messageId ?? last.id ?? liveId;
      liveId = settledId;
      msgs[idx] = {
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
        cards: cardsCollected.length > 0 ? cardsCollected as unknown as Message["cards"] : undefined,
        matchedSkills: currentMatchedSkills,
        // 落库了就用真实 id 换掉临时 id（换完 isPersistedId 才为真，
        // 悬浮的阅读/删除按钮、过程记录加载才允许发请求）
        id: settledId,
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
      cards: cardsCollected.length > 0 ? cardsCollected as unknown as Message["cards"] : undefined,
      matchedSkills: currentMatchedSkills,
      // 兜底：没有占位气泡可改时新加一条，同样优先用真实 id
      id: messageId ?? placeholderId,
      intermediateOutput: intermediateOutput || undefined,
      model: finalModel,
      error: lastError || undefined,
    }];
  });
  cancelScheduledFlush();
  setBgPolling(null);
  setStopping(false);
  setStreaming(false);
  setConsentRequest(null);
  setCleanupConfirm(null);
  setAskUserRequest(null);
  setWaitForUserRequest(null);
  // run 结束：待处理补充信息区清空（后端同样在 run 收尾清空 DB 镜像）
  writeActive(() => setPendingInjected([]));
}
