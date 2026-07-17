import { useState, useEffect } from "react";
import { fetchSessions, createSession, deleteSession, type SessionInfo } from "../lib/api";

interface Props {
  currentSession: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: (id: string) => void;
  onOpenSettings: () => void;
}

export default function Sidebar({ currentSession, onSelectSession, onNewChat, onOpenSettings }: Props) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  useEffect(() => {
    loadSessions();
  }, []);

  async function loadSessions() {
    try {
      const list = await fetchSessions(50);
      setSessions(list);
    } catch { /* backend not available */ }
  }

  async function handleNew() {
    try {
      const s = await createSession();
      setSessions((prev) => [{ ...s, created_at: Date.now() / 1000, updated_at: Date.now() / 1000 }, ...prev]);
      onNewChat(s.id);
    } catch { /* ignore */ }
  }

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    await deleteSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (currentSession === id) onNewChat("");
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <button className="btn-new" onClick={handleNew}>+ New Chat</button>
        <button className="btn-icon" onClick={onOpenSettings} title="Settings">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
          </svg>
        </button>
      </div>
      <div className="session-list">
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`session-item ${s.id === currentSession ? "active" : ""}`}
            onClick={() => onSelectSession(s.id)}
          >
            <span className="session-title">{s.title || "New Chat"}</span>
            <button className="btn-delete" onClick={(e) => handleDelete(e, s.id)} title="Delete">×</button>
          </div>
        ))}
      </div>
    </aside>
  );
}
