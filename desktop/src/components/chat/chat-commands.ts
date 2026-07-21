import {
  createSession,
  fetchSession,
  fetchSessions,
  compactSession,
  summarySession,
  stopGeneration,
} from "@/lib/api";
import type { Message, Usage, Quote, PendingFile } from "@ethan/shared/chat/types";

export interface HandleCommandActions {
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  setActiveSession: (id: string | null) => void;
  setSessionTitle: (title: string) => void;
  setSessionUsage: (usage: Usage) => void;
  setPendingFiles: (files: PendingFile[]) => void;
  setQuote: (q: Quote | null) => void;
  setStreaming: (v: boolean) => void;
  selectedModel: string;
  mode: string;
  activeSession: string | null;
}

// 处理 /command 命令。返回 true 表示已拦截处理，调用方无需继续。
export async function handleCommand(
  trimmed: string,
  actions: HandleCommandActions,
): Promise<boolean> {
  const {
    setMessages, setActiveSession, setSessionTitle,
    setSessionUsage, setPendingFiles, setQuote, setStreaming,
    selectedModel, mode, activeSession,
  } = actions;

  const [cmd, ...rest] = trimmed.slice(1).split(/\s+/);
  const arg = rest.join(" ").trim();
  const now = Date.now() / 1000;
  const pushAssistant = (content: string) =>
    setMessages((prev) => [...prev, { role: "assistant", content, created_at: now }]);

  if (cmd === "new") {
    const s = await createSession(selectedModel, mode, "desktop");
    setActiveSession(s.id);
    setSessionTitle("新对话");
    setMessages([]);
    setSessionUsage({ input: 0, output: 0, cache: 0 });
    setPendingFiles([]);
    setQuote(null);
    window.history.replaceState(null, "", `/chat/${s.id}/`);
    return true;
  }
  if (cmd === "help") {
    pushAssistant(
      "🛠 **可用命令**\n\n" +
      "- `/new` — 新建对话，清空当前上下文\n" +
      "- `/compact` — 压缩历史对话为摘要，释放上下文\n" +
      "- `/summary` — 生成当前会话的总结\n" +
      "- `/sessions` — 列出最近的会话\n" +
      "- `/stop` — 停止当前进行中的回复\n" +
      "- `/btw <问题>` — 不带历史的单轮轻量查询\n" +
      "- `/review <链接>` — Code review：加载 review 技能分析代码\n" +
      "- `/help` — 显示本帮助\n\n" +
      "（`/model` `/token` 请用顶部下拉和设置页；其它消息正常对话即可）"
    );
    return true;
  }
  if (cmd === "compact") {
    if (!activeSession) {
      pushAssistant("⚠️ 当前没有会话，先聊几句再 `/compact` 吧~");
      return true;
    }
    setStreaming(true);
    try {
      const r = await compactSession(activeSession);
      const detail = await fetchSession(activeSession);
      setMessages(
        detail.messages.map((m: any) => ({
          role: m.role,
          content: m.content,
          created_at: m.created_at,
          usage: m.usage || undefined,
          toolsExpanded: false,
        }))
      );
      pushAssistant(`🧠 **已压缩历史**\n\n> ${r.summary.slice(0, 300)}${r.summary.length > 300 ? "…" : ""}\n\n继续聊吧~`);
    } catch (e) {
      pushAssistant(`⚠️ 压缩失败：${e instanceof Error ? e.message : "未知错误"}`);
    } finally {
      setStreaming(false);
    }
    return true;
  }
  if (cmd === "summary") {
    if (!activeSession) {
      pushAssistant("⚠️ 当前没有会话，先聊几句再 `/summary` 吧~");
      return true;
    }
    setStreaming(true);
    try {
      const r = await summarySession(activeSession);
      pushAssistant(r.summary);
    } catch (e) {
      pushAssistant(`⚠️ 总结失败：${e instanceof Error ? e.message : "未知错误"}`);
    } finally {
      setStreaming(false);
    }
    return true;
  }
  if (cmd === "sessions") {
    try {
      const list = await fetchSessions(8, 0);
      if (!list.length) {
        pushAssistant("暂无会话。");
      } else {
        const body = list
          .map((s) => `- \`${s.id.slice(-10)}\`  ${s.title || "（无标题）"}`)
          .join("\n");
        pushAssistant(`📋 **最近会话**\n\n${body}\n\n点击左侧侧栏可切换。`);
      }
    } catch {
      pushAssistant("⚠️ 获取会话列表失败。");
    }
    return true;
  }
  if (cmd === "stop") {
    if (activeSession) {
      await stopGeneration(activeSession).catch(() => {});
    }
    return true;
  }
  // 未知命令
  pushAssistant(`未知命令：\`/${cmd}\`\n\n输入 \`/help\` 查看可用命令。`);
  return true;
}
