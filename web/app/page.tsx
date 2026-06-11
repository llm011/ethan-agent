"use client";

import { useAuth } from "@/lib/auth-context";
import { AuthProvider } from "@/lib/auth-context";
import { ChatView } from "@/components/chat-view";
import { LoginView } from "@/components/login-view";

function AppContent() {
  const { authenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  if (!authenticated) return <LoginView />;
  return <ChatView />;
}

export default function Home() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
