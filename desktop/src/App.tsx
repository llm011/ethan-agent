import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";

function App() {
  const [messages, setMessages] = useState<
    { role: "user" | "assistant"; content: string }[]
  >([]);
  const [input, setInput] = useState("");

  async function handleSend() {
    if (!input.trim()) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);

    // TODO: connect to Ethan Agent backend
    const reply: string = await invoke("greet", { name: userMsg });
    setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
  }

  return (
    <div className="app">
      <header className="titlebar">
        <h1>Ethan Agent</h1>
      </header>

      <main className="chat-container">
        {messages.length === 0 && (
          <div className="empty-state">
            <div className="logo">E</div>
            <p>How can I help you today?</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            <div className="bubble">{msg.content}</div>
          </div>
        ))}
      </main>

      <footer className="input-area">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Type a message..."
          autoFocus
        />
        <button onClick={handleSend}>Send</button>
      </footer>
    </div>
  );
}

export default App;
