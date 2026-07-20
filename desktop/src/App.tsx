import { HashRouter, Routes, Route, Navigate, useParams, useNavigate } from "react-router-dom";
import { type ModelEntry } from "@/lib/api";
import { fetchModels } from "@/lib/api-base";
import { useCachedResource } from "@/lib/use-cached-resource";
import { AuthProvider } from "@/lib/auth-context";
import { LayoutShell } from "@/components/layout-shell";
import { ChatView } from "@/components/chat-view";
import { AllSessionsView } from "@/components/all-sessions-view";
import { MemoryView } from "@/components/memory-view";
import { KnowledgeView } from "@/components/knowledge-view";
import { SkillsView } from "@/components/skills-view";
import { ScheduleView } from "@/components/schedule-view";
import { BackgroundTasksView } from "@/components/background-tasks-view";
import { SettingsView } from "@/components/settings-view";
import { ToolTiersView } from "@/components/tool-tiers-view";
import { ChannelsView } from "@/components/channels-view";
import { LogsView } from "@/components/logs-view";
import { DocsView } from "@/components/docs-view";

/** Chat 路由：从 URL 提取 sessionId 传给 ChatView */
function ChatRoute() {
  const { sessionId } = useParams<{ sessionId?: string }>();
  return <ChatView initialSessionId={sessionId} />;
}


function SessionsRoute() {
  const navigate = useNavigate();
  return (
    <AllSessionsView onSelectSession={(id) => navigate(`/chat/${id}`)} />
  );
}

function SettingsRoute() {
  const { tab } = useParams<{ tab?: string }>();
  // models 是 A 类准静态数据，进 settings 时命中缓存 0ms 渲染；
  // 写操作（addModel/deleteModel）会 bustCache("models")，本 hook 自动 refetch
  const { data: models } = useCachedResource<ModelEntry[]>("models", fetchModels, { ttlMs: 60 * 60_000 });
  const VALID_TABS = ["general", "providers", "channels", "identity", "soul", "tools", "heartbeat", "profile", "prompt-preview", "api-keys", "fast-rules"];
  const initialTab = tab && VALID_TABS.includes(tab) ? tab : "general";
  return (
    <div className="flex flex-col flex-1 h-full min-h-0">
      <SettingsView models={models ?? []} initialTab={initialTab as any} />
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <HashRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route element={<LayoutShell />}>
            <Route path="/chat" element={<ChatRoute />} />
            <Route path="/chat/:sessionId" element={<ChatRoute />} />
            <Route path="/sessions" element={<SessionsRoute />} />
            <Route path="/memory" element={<MemoryView />} />
            <Route path="/knowledge" element={<KnowledgeView />} />
            <Route path="/skills" element={<SkillsView />} />
            <Route path="/schedule" element={<ScheduleView />} />
            <Route path="/background-tasks" element={<BackgroundTasksView />} />
            <Route path="/settings" element={<Navigate to="/settings/general" replace />} />
            <Route path="/settings/:tab" element={<SettingsRoute />} />
            <Route path="/tool-tiers" element={<ToolTiersView />} />
            <Route path="/channels" element={<ChannelsView />} />
            <Route path="/logs" element={<LogsView />} />
            <Route path="/docs" element={<DocsView />} />
            <Route path="/docs/:slug" element={<DocsView />} />
          </Route>
        </Routes>
      </HashRouter>
    </AuthProvider>
  );
}

export default App;
