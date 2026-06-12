"use client";

import { useAuth } from "@/lib/auth-context";
import { LoginView } from "@/components/login-view";
import { Sidebar } from "@/components/sidebar";
import { useState, useEffect, createContext, useContext } from "react";
import { ChevronLeft, ChevronRight, Menu } from "lucide-react";

// Shared context so child views (chat-view, etc.) can toggle the sidebar
export const SidebarContext = createContext<{
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}>({ sidebarOpen: true, setSidebarOpen: () => {} });

export function useSidebar() {
  return useContext(SidebarContext);
}

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const { authenticated, loading } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Start closed on mobile to avoid the overlay flashing open on load
  useEffect(() => {
    if (window.innerWidth < 768) {
      setSidebarOpen(false);
    }
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  if (!authenticated) return <LoginView />;

  return (
    <SidebarContext.Provider value={{ sidebarOpen, setSidebarOpen }}>
      <div className="flex h-screen bg-background overflow-hidden">
        {/* Mobile overlay backdrop — click to close sidebar */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-30 bg-black/50 md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Sidebar
            Mobile: fixed overlay (z-40, w-72, shadow) when open; hidden when closed
            Desktop: inline (relative, w-64) when open; collapsed (w-0) when closed */}
        <div
          className={`
            flex flex-col shrink-0 transition-all duration-200
            ${
              sidebarOpen
                ? "fixed inset-y-0 left-0 z-40 w-72 shadow-xl md:shadow-none md:relative md:z-auto md:inset-auto md:w-64"
                : "hidden md:flex md:w-0 md:overflow-hidden"
            }
          `}
        >
          <Sidebar />
        </div>

        {/* Desktop-only sidebar collapse toggle (the little chevron on the border) */}
        <div className="relative hidden md:flex flex-col shrink-0">
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
        <main className="flex-1 flex flex-col min-w-0 relative">
          {/* Mobile hamburger — shown on all pages when sidebar is closed */}
          {!sidebarOpen && (
            <button
              onClick={() => setSidebarOpen(true)}
              className="md:hidden absolute top-3 left-3 z-20 w-11 h-11 flex items-center justify-center rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
          )}
          {children}
        </main>
      </div>
    </SidebarContext.Provider>
  );
}
