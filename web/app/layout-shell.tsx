"use client";

import { useAuth } from "@/lib/auth-context";
import { LoginView } from "@/components/login-view";
import { Sidebar } from "@/components/sidebar";
import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const { authenticated, loading } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(true);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  if (!authenticated) return <LoginView />;

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <div
        className={`${
          sidebarOpen ? "w-64" : "w-0 overflow-hidden"
        } transition-all duration-200 shrink-0`}
      >
        <Sidebar />
      </div>

      {/* Sidebar collapse toggle */}
      <div className="relative flex flex-col shrink-0">
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="absolute -left-3 top-1/2 -translate-y-1/2 z-10 w-6 h-12 flex items-center justify-center rounded-full bg-background border border-border hover:bg-muted hover:border-primary transition-all shadow-sm text-muted-foreground hover:text-foreground"
          title={sidebarOpen ? "收起侧边栏" : "展开侧边栏"}
        >
          {sidebarOpen ? (
            <ChevronLeft className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </button>
      </div>

      {/* Main content */}
      <main className="flex-1 flex flex-col min-w-0">{children}</main>
    </div>
  );
}
