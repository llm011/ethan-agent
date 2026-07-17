import { useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import Settings from "./components/Settings";
import "./styles.css";

function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="app">
      <div className="titlebar" data-tauri-drag-region>
        <span className="titlebar-title">Ethan Agent</span>
      </div>

      <div className="app-body">
        <Sidebar
          currentSession={sessionId}
          onSelectSession={setSessionId}
          onNewChat={(id) => setSessionId(id || null)}
          onOpenSettings={() => setSettingsOpen(true)}
        />
        <ChatView sessionId={sessionId} />
      </div>

      <Settings open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

export default App;
