import { useState, useRef, useEffect } from "react";
import {
  streamChat,
  streamResume,
  stopGeneration,
  fetchSession,
  type ChatMessage,
  type StreamChunk,
  type SessionMessage,
} from "../lib/api";

interface ToolStep {
  tool: string;
  args: string;
  state: string;
  duration_ms?: number | null;
  result_preview?: string;
}

interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
  toolSteps?: ToolStep[];
}

interface Props {
  sessionId: string | null;
}

export default function ChatView({ sessionId }: Props) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef(false);

  useEffect(() => {
    if (sessionId) {
      loadSession(sessionId);
    } else {
      setMessages([]);
    }
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function loadSession(id: string) {
    try {
      const detail = await fetchSession(id);
      const msgs: DisplayMessage[] = detail.messages.map((m: SessionMessage) => ({
        role: m.role as "user" | "assistant",
        content: m.content,
        toolSteps: m.tool_steps,
      }));
      setMessages(msgs);

      if (detail.active_run) {
        const gen = await streamResume(id);
        if (gen) consumeStream(gen);
      }
    } catch { /* ignore */ }
  }

  async function handleSend() {
    if (!input.trim() || streaming) return;
    const userMsg = input.trim();
    setInput("");

    const newMessages: DisplayMessage[] = [...messages, { role: "user", content: userMsg }];
    setMessages(newMessages);

    const chatMessages: ChatMessage[] = newMessages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    setStreaming(true);
    abortRef.current = false;

    try {
      const stream = streamChat(chatMessages, undefined, sessionId || undefined);
      consumeStream(stream);
    } catch {
      setStreaming(false);
    }
  }

  async function consumeStream(stream: AsyncGenerator<StreamChunk>) {
    setStreaming(true);
    let assistantContent = "";
    const toolSteps: ToolStep[] = [];

    setMessages((prev) => [...prev, { role: "assistant", content: "", toolSteps: [] }]);

    try {
      for await (const chunk of stream) {
        if (abortRef.current) break;

        if (chunk.content) {
          assistantContent += chunk.content;
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = {
              role: "assistant",
              content: assistantContent,
              toolSteps: [...toolSteps],
            };
            return updated;
          });
        }

        if (chunk.tool && chunk.state === "start") {
          toolSteps.push({ tool: chunk.tool, args: chunk.args || "", state: "running" });
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = {
              role: "assistant",
              content: assistantContent,
              toolSteps: [...toolSteps],
            };
            return updated;
          });
        }

        if (chunk.tool && (chunk.state === "done" || chunk.state === "error")) {
          const idx = toolSteps.findIndex((t) => t.tool === chunk.tool && t.state === "running");
          if (idx >= 0) {
            toolSteps[idx] = {
              ...toolSteps[idx],
              state: chunk.state,
              duration_ms: chunk.duration_ms,
              result_preview: chunk.result_preview,
            };
          }
        }

        if (chunk.error) {
          assistantContent += `\n\n**Error:** ${chunk.error}`;
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { role: "assistant", content: assistantContent, toolSteps: [...toolSteps] };
            return updated;
          });
        }

        if (chunk.stopped) {
          assistantContent += "\n\n*[Generation stopped]*";
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { role: "assistant", content: assistantContent, toolSteps: [...toolSteps] };
            return updated;
          });
        }
      }
    } catch (e) {
      if (!abortRef.current) {
        assistantContent += `\n\n**Error:** ${e instanceof Error ? e.message : "Stream failed"}`;
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = { role: "assistant", content: assistantContent, toolSteps: [...toolSteps] };
          return updated;
        });
      }
    }

    setStreaming(false);
  }

  async function handleStop() {
    abortRef.current = true;
    if (sessionId) await stopGeneration(sessionId);
    setStreaming(false);
  }

  return (
    <main className="chat-container">
      {messages.length === 0 && (
        <div className="empty-state">
          <img src="/logo-fox.jpg" alt="Ethan" className="logo-img" />
          <p>How can I help you today?</p>
        </div>
      )}

      <div className="messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            {msg.toolSteps && msg.toolSteps.length > 0 && (
              <div className="tool-steps">
                {msg.toolSteps.map((step, j) => (
                  <div key={j} className={`tool-step ${step.state}`}>
                    <span className="tool-name">{step.tool}</span>
                    <span className="tool-state">
                      {step.state === "running" ? "..." : step.state === "done" ? `${step.duration_ms ?? ""}ms` : "failed"}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="bubble">{msg.content || (streaming && i === messages.length - 1 ? "..." : "")}</div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <footer className="input-area">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
          placeholder="Type a message..."
          disabled={streaming}
          autoFocus
        />
        {streaming ? (
          <button className="btn-stop" onClick={handleStop}>Stop</button>
        ) : (
          <button onClick={handleSend} disabled={!input.trim()}>Send</button>
        )}
      </footer>
    </main>
  );
}
