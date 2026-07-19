import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getApiUrl, setApiUrl } from "@/lib/api-base";
import { ChevronDown, ChevronUp, Server } from "lucide-react";

export function LoginView() {
  const { login } = useAuth();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  // 桌面端专属：可折叠的 API 地址输入框（web 端不需要，走同源）
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [apiUrl, setApiUrlState] = useState(getApiUrl());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    // 先把用户填的 API 地址存下来，再尝试登录
    if (apiUrl !== getApiUrl()) {
      setApiUrl(apiUrl);
    }
    try {
      const ok = await login(token);
      if (!ok) setError("Invalid token");
    } catch (err) {
      setError("无法连接到后端服务，请检查 API 地址是否可达");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center h-screen bg-background">
        <div className="w-full max-w-sm space-y-6 p-8" data-tauri-drag-region>
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">Ethan</h1>
          <p className="text-muted-foreground text-sm">Enter your access token to continue</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            type="password"
            placeholder="Access token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoFocus
          />
          {error && <p className="text-destructive text-sm">{error}</p>}

          {/* 桌面端专属：API 地址配置（默认折叠） */}
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <Server className="h-3 w-3" />
              高级设置
              {showAdvanced ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </button>
            {showAdvanced && (
              <div className="space-y-1 rounded-md border bg-muted/30 p-3">
                <label className="text-xs text-muted-foreground">API 地址</label>
                <Input
                  type="text"
                  value={apiUrl}
                  onChange={(e) => setApiUrlState(e.target.value)}
                  placeholder="http://127.0.0.1:8989/api"
                  className="text-xs font-mono"
                />
                <p className="text-[10px] text-muted-foreground">
                  桌面端通过此地址连接后端 Ethan Agent 服务。
                </p>
              </div>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Verifying..." : "Login"}
          </Button>
        </form>
      </div>
    </div>
  );
}
