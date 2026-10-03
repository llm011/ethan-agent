"use client";

import { useAuth } from "@/lib/auth-context";
import { LoginView } from "@/components/login-view";
import { Sidebar } from "@/components/sidebar";
import { useState, useEffect, createContext, useContext, useCallback, useRef } from "react";
import { ChevronLeft, ChevronRight, Menu } from "lucide-react";
import { PreviewProvider } from "@/components/preview-panel/preview-context";
import { ResizeHandle } from "@/components/preview-panel/resize-handle";

// 侧边栏宽度（px）。用 px 而非百分比：侧边栏装的是导航项，宽度与视口无关，
// 窗口拉宽时它不该跟着变胖。
const SIDEBAR_KEY = "ethan:sidebar-width";
const SIDEBAR_DEFAULT = 256;   // 与原先的 w-64 一致
const SIDEBAR_MIN = 180;
const SIDEBAR_MAX = 420;

function readSidebarWidth(): number {
  if (typeof window === "undefined") return SIDEBAR_DEFAULT;
  try {
    const n = Number(localStorage.getItem(SIDEBAR_KEY));
    if (!Number.isFinite(n) || n <= 0) return SIDEBAR_DEFAULT;
    return Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, n));
  } catch {
    return SIDEBAR_DEFAULT;
  }
}

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
  // 侧边栏宽度（px，可拖拽）。初始用默认值，挂载后再读 localStorage——
  // 避免 SSR 与客户端首帧不一致导致 hydration mismatch。
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const sidebarWidthRef = useRef(SIDEBAR_DEFAULT);
  // 拖动中要关掉宽度过渡：内层 div 的 transition-all 本是给展开/收起做动画的，
  // 拖拽时会让面板慢半拍地追光标（实测落后 70px+）。松手后再恢复过渡。
  const [resizing, setResizing] = useState(false);

  useEffect(() => {
    const stored = readSidebarWidth();
    sidebarWidthRef.current = stored;
    setSidebarWidth(stored);
  }, []);

  // Start closed on mobile to avoid the overlay flashing open on load
  useEffect(() => {
    if (window.innerWidth < 768) {
      setSidebarOpen(false);
    }
  }, []);

  const handleSidebarResize = useCallback((deltaX: number) => {
    // 侧边栏在左侧：向右拖（deltaX > 0）变宽
    setResizing(true);
    const next = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, sidebarWidthRef.current + deltaX));
    setSidebarWidth(next);
  }, []);

  const handleSidebarResizeEnd = useCallback(() => {
    setResizing(false);
    setSidebarWidth((current) => {
      sidebarWidthRef.current = current;
      try {
        localStorage.setItem(SIDEBAR_KEY, String(Math.round(current)));
      } catch {}
      return current;
    });
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
      <PreviewProvider>
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
            Desktop: inline when open, 宽度可拖拽（默认 256 = 原先的 w-64）；collapsed (w-0) when closed
            窄屏用 w-72 固定宽度：移动端是覆盖式抽屉，拖拽宽度没有意义。
            桌面端外层也要 md:w-[var(--sb-w)]：折叠箭头和 HeaderFillet 都按外层右缘定位，
            外层若停留在 w-72（288px），面板 256px 时它们会悬空在 32px 的空档上。
            拖拽中 md:transition-none 关掉宽度过渡防黏滞；展开/收起动画仍走 transition-all */}
        <div
          className={`
            flex flex-col shrink-0 transition-all duration-200
            ${
              sidebarOpen
                ? `fixed inset-y-0 left-0 z-40 w-72 shadow-xl md:shadow-none md:relative md:z-auto md:inset-auto md:w-[var(--sb-w)]${resizing ? " md:transition-none" : ""}`
                : "hidden md:flex md:w-0 md:overflow-hidden"
            }
          `}
          style={sidebarOpen ? ({ "--sb-w": `${sidebarWidth}px` } as React.CSSProperties) : undefined}
        >
          {/* 内层保持固定宽度：收起动画时外层 w-0 渐收、overflow-hidden 裁切，
              内容宽度不变才能呈现「滑出」而不是「压扁」 */}
          <div className="relative flex flex-col w-full h-full md:w-[var(--sb-w)]">
            <Sidebar />
            {/* 分隔线：仅桌面端、且侧边栏打开时——收起态没有可拖的边界。
                overlay + edge=right：压在 sidebar 自带的 border-r 上（右侧那条），
                不占布局宽度 */}
            {sidebarOpen && (
              <div className="hidden md:block">
                <ResizeHandle
                  variant="overlay"
                  edge="right"
                  onResize={handleSidebarResize}
                  onResizeEnd={handleSidebarResizeEnd}
                />
              </div>
            )}
          </div>
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

        {/* Mobile hamburger — outside main to avoid overflow:hidden issues */}
        {!sidebarOpen && (
          <button
            onClick={() => setSidebarOpen(true)}
            className="md:hidden fixed top-3 left-3 z-50 w-10 h-10 flex items-center justify-center rounded-full bg-background border border-border shadow-md text-foreground active:scale-95 transition-transform"
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </button>
        )}

        {/* Main content
            注意：不要加 overflow-hidden —— HeaderFillet 需要向左溢出 1px 覆盖 sidebar 的 border-r；
            垂直/水平溢出由外层 h-screen overflow-hidden 兜底 */}
        <main className="flex-1 flex flex-col min-w-0 relative">
          {children}
        </main>
      </div>
      </PreviewProvider>
    </SidebarContext.Provider>
  );
}
