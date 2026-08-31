"use client";

import { AuthProvider } from "@/lib/auth-context";
import { UpdateToast } from "@/components/update-toast";
import { Toaster } from "@ethan/shared/components/toaster";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <UpdateToast />
      <Toaster />
      {children}
    </AuthProvider>
  );
}
