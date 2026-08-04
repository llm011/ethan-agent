"use client";

import { AuthProvider } from "@/lib/auth-context";
import { UpdateToast } from "@/components/update-toast";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <UpdateToast />
      {children}
    </AuthProvider>
  );
}
