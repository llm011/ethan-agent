"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@ethan/shared/ui/button";
import { Input } from "@ethan/shared/ui/input";

export function LoginView() {
  const { login } = useAuth();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    const ok = await login(token);
    setLoading(false);
    if (!ok) setError("Invalid token");
  };

  return (
    <div className="flex items-center justify-center h-screen bg-background">
      <div className="w-full max-w-sm space-y-6 p-8">
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">Ethan Agent</h1>
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
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Verifying..." : "Login"}
          </Button>
        </form>
      </div>
    </div>
  );
}
