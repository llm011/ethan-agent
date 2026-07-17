import { useState, useEffect } from "react";
import { getApiUrl, setApiUrl, getAuthToken, setAuthToken, fetchHealth, verifyAuth } from "../lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function Settings({ open, onClose }: Props) {
  const [url, setUrl] = useState(getApiUrl());
  const [token, setToken] = useState(getAuthToken());
  const [status, setStatus] = useState<"idle" | "checking" | "ok" | "error">("idle");
  const [version, setVersion] = useState("");

  useEffect(() => {
    if (open) {
      setUrl(getApiUrl());
      setToken(getAuthToken());
      setStatus("idle");
    }
  }, [open]);

  async function handleTest() {
    setStatus("checking");
    setApiUrl(url);
    const health = await fetchHealth();
    if (health) {
      setVersion(health.version || "");
      if (token) {
        const ok = await verifyAuth(token);
        setStatus(ok ? "ok" : "error");
      } else {
        setStatus("ok");
      }
    } else {
      setStatus("error");
    }
  }

  function handleSave() {
    setApiUrl(url);
    setAuthToken(token);
    onClose();
  }

  if (!open) return null;

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <h2>Settings</h2>

        <label>
          Backend API URL
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="http://127.0.0.1:8900/api"
          />
        </label>

        <label>
          Auth Token (optional)
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Leave empty if no auth required"
          />
        </label>

        <div className="settings-actions">
          <button className="btn-secondary" onClick={handleTest}>
            {status === "checking" ? "Testing..." : "Test Connection"}
          </button>
          <button className="btn-primary" onClick={handleSave}>
            Save
          </button>
        </div>

        {status === "ok" && (
          <div className="status-msg success">
            Connected{version ? ` (v${version})` : ""}
          </div>
        )}
        {status === "error" && (
          <div className="status-msg error">Connection failed. Check URL and token.</div>
        )}
      </div>
    </div>
  );
}
